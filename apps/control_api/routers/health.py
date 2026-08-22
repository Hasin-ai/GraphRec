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

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from graphrec.common.config import Settings, get_settings

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


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReadinessResponse:
    """Readiness. Each dependency is probed and reported independently.

    Phase 1 has no database session or Redis client yet, so both are reported
    `unavailable` rather than `pass` — claiming a check passed when it was never
    run is the failure mode this endpoint exists to prevent. Phase 2 replaces
    these with real probes.
    """
    checks = [
        DependencyCheck(
            name="postgres",
            status=CheckStatus.UNAVAILABLE,
            detail="not probed until the session factory lands in Phase 2",
        ),
        DependencyCheck(
            name="redis",
            status=CheckStatus.UNAVAILABLE,
            detail="not probed until the client lands in Phase 2",
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
