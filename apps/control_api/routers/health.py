"""Liveness and readiness.

`/healthz` answers "is this process alive" and must never touch a dependency:
a health check that fails because Redis is slow will cause an orchestrator to
kill a process that was working fine.

`/readyz` answers "should this process receive traffic" and therefore does check
dependencies, reporting each one separately. It degrades rather than lying: an
unavailable check is reported as `unavailable`, never as a zero or a pass
(the same rule the console applies to measurements, UC-30).
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from graphrec.common.config import Settings, get_settings
from graphrec.common.logging import get_logger

logger = get_logger(__name__)

#: A readiness probe that can hang is worse than one that fails: an orchestrator
#: waiting on it learns nothing and routes nowhere.
PROBE_TIMEOUT_SECONDS = 2.0

router = APIRouter(tags=["health"])


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNAVAILABLE = "unavailable"


class DependencyCheck(BaseModel):
    name: str
    status: CheckStatus
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadinessResponse(BaseModel):
    status: CheckStatus
    checks: list[DependencyCheck]


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Liveness. Deliberately dependency-free."""
    return HealthResponse(status="ok", version="0.1.0")


async def _probe_postgres(request: Request) -> DependencyCheck:
    """`SELECT 1` on the application engine — the role that serves traffic.

    Probed as `graphrec_app` rather than as the owner on purpose: what readiness
    means here is "the role this process actually uses can reach the database",
    and a probe on a different connection can pass while the real one cannot.

    No tenant context is bound and none is needed. `SELECT 1` reads no table, so
    row-level security has nothing to filter, and the probe cannot become an
    accidental way to read across tenants.
    """
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            sessionmaker = request.app.state.sessionmaker
            async with sessionmaker() as session:
                await session.execute(sa.text("SELECT 1"))
    except TimeoutError:
        return DependencyCheck(
            name="postgres",
            status=CheckStatus.FAIL,
            detail=f"did not answer within {PROBE_TIMEOUT_SECONDS:g}s",
        )
    except Exception:
        # The exception is logged, not returned. A connection error carries the
        # host, the port and sometimes the role — none of which belongs in a
        # response body that is typically unauthenticated (NR-NF-06).
        logger.exception("readiness_probe_failed", extra={"dependency": "postgres"})
        return DependencyCheck(name="postgres", status=CheckStatus.FAIL, detail="unreachable")
    return DependencyCheck(name="postgres", status=CheckStatus.PASS)


async def _probe_redis(request: Request) -> DependencyCheck:
    """`PING` on the same client the metering counters use.

    Redis being down is not the same class of failure as PostgreSQL being down,
    and the report says so. Counters degrade rather than refuse
    (`ResilientUsageCounters`), so a process with no cache can still serve
    every read and every write that does not meter — it is `unavailable`, not
    `fail`, and the overall verdict below keeps it out of `pass` without
    calling it broken.
    """
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await request.app.state.redis.ping()
    except TimeoutError:
        return DependencyCheck(
            name="redis",
            status=CheckStatus.UNAVAILABLE,
            detail=f"did not answer within {PROBE_TIMEOUT_SECONDS:g}s",
        )
    except Exception:
        logger.exception("readiness_probe_failed", extra={"dependency": "redis"})
        return DependencyCheck(name="redis", status=CheckStatus.UNAVAILABLE, detail="unreachable")
    return DependencyCheck(name="redis", status=CheckStatus.PASS)


async def _probe_object_storage(request: Request) -> DependencyCheck:
    """`ArtifactStore.probe` — a `HEAD` on the bucket, or a writable root.

    Run on a thread because the store is synchronous by design (see
    `graphrec.storage.store`): every other caller is a worker with nothing else
    to do, and this endpoint is the one place that does. Without the thread a
    slow endpoint would block the event loop, which is precisely the failure a
    readiness probe is supposed to report rather than cause.

    A `fail`, not an `unavailable`: unlike the cache, there is no degraded mode
    here. A control API that cannot reach object storage cannot serve an
    artifact download or accept an upload, and traffic sent to it will fail.
    """
    store = request.app.state.artifact_store
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await asyncio.to_thread(store.probe)
    except TimeoutError:
        return DependencyCheck(
            name="object_storage",
            status=CheckStatus.FAIL,
            detail=f"did not answer within {PROBE_TIMEOUT_SECONDS:g}s",
        )
    except Exception:
        logger.exception("readiness_probe_failed", extra={"dependency": "object_storage"})
        return DependencyCheck(name="object_storage", status=CheckStatus.FAIL, detail="unreachable")
    return DependencyCheck(name="object_storage", status=CheckStatus.PASS)


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessResponse:
    """Readiness. Each dependency is probed and reported independently.

    All three are probed for real. The rule the module docstring states is the
    one that matters here: a check that was not run is reported `unavailable`,
    never `pass`, because a probe that lies about having run is worse than no
    probe at all — it is the one that gets traffic routed to a process that
    cannot serve it.

    `unavailable` and `fail` are kept apart because they mean different things
    to whoever reads this. `fail` is a dependency without which this process
    cannot do its job. `unavailable` is one it can degrade around, and Redis is
    the only such dependency: metering falls back to an in-memory counter.
    Neither is `pass`, so neither gets traffic — but an operator reading the
    body can tell a cache outage from a database outage without leaving the
    page.

    The three probes run concurrently. Serially they would take up to three
    timeouts to answer, and a readiness endpoint that takes six seconds to say
    "not ready" has already been given up on by the thing that asked.
    """
    checks = list(
        await asyncio.gather(
            _probe_postgres(request),
            _probe_redis(request),
            _probe_object_storage(request),
        )
    )

    if any(check.status is CheckStatus.FAIL for check in checks):
        overall = CheckStatus.FAIL
    elif any(check.status is CheckStatus.UNAVAILABLE for check in checks):
        overall = CheckStatus.UNAVAILABLE
    else:
        overall = CheckStatus.PASS

    # Not ready is a 503: an orchestrator must not route to this process yet.
    if overall is not CheckStatus.PASS:
        response.status_code = 503

    return ReadinessResponse(status=overall, checks=checks)
