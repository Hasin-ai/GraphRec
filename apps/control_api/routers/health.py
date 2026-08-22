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


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessResponse:
    """Readiness. Each dependency is probed and reported independently.

    PostgreSQL is probed for real from Phase 2. Redis and object storage have no
    client yet and are reported `unavailable` rather than `pass` — claiming a
    check passed when it was never run is the failure mode this endpoint exists
    to prevent, and it is why `unavailable` is a distinct value from `fail`.

    The consequence, which is intended: this endpoint answers 503 until every
    dependency is genuinely probed. A process that has not proven it can serve
    should not be sent traffic.
    """
    checks = [
        await _probe_postgres(request),
        DependencyCheck(
            name="redis",
            status=CheckStatus.UNAVAILABLE,
            detail="not probed until the client lands in Phase 5",
        ),
        DependencyCheck(
            name="object_storage",
            status=CheckStatus.UNAVAILABLE,
            detail="not probed until the storage client lands in Phase 8",
        ),
    ]

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
