from __future__ import annotations

from uuid import UUID

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.registration.rate_limit import SharedRateLimiter
from graphrec_core.schemas.usage import Granularity, UsageSummaryResponse, UsageTrendResponse
from graphrec_core.usage.trends import usage_trend
from graphrec_core.settings import get_settings
from graphrec_core.usage.service import UsageService

router = APIRouter(prefix="/v1", tags=["usage"])
settings = get_settings()
usage_limiter = SharedRateLimiter(
    name="usage",
    limit=settings.usage_rate_limit,
    window_seconds=settings.usage_rate_window_seconds,
)


MAX_PERIODS_BACK = 24


def _parse_period(value: str | None) -> datetime | None:
    if value is None:
        return None
    invalid = ApiError(422, "validation_failed", "period must be a month within the last 24 months, as YYYY-MM",
                       details={"fields": [{"field": "period", "message": "Invalid period"}]})
    try:
        year, month = (int(part) for part in value.split("-"))
        start = datetime(year, month, 1, tzinfo=timezone.utc)
    except ValueError as exc:
        raise invalid from exc
    now = datetime.now(timezone.utc)
    back = (now.year - start.year) * 12 + now.month - start.month
    if back < 0 or back > MAX_PERIODS_BACK:
        raise invalid
    return start


@router.get("/usage", response_model=UsageSummaryResponse)
def get_usage(
    request: Request,
    period: str | None = Query(None, description="UC-24: a monthly billing period, YYYY-MM (default: the current one). "
                                                  "Up to 24 months back; never in the future.", pattern=r"^\d{4}-\d{2}$"),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> UsageSummaryResponse:
    principal.require_scope("usage:read")
    unexpected = sorted(set(request.query_params.keys()) - {"period"})
    if unexpected:
        raise ApiError(
            422,
            "validation_failed",
            "Only the period query parameter is accepted",
            details={"fields": [{"field": key, "message": "Unexpected query parameter"} for key in unexpected]},
        )
    month = _parse_period(period)

    retry_after = usage_limiter.check(principal.limiter_subject)
    if retry_after is not None:
        raise ApiError(
            429,
            "rate_limit_exceeded",
            "Usage read limit exceeded",
            retryable=True,
            retry_after_seconds=retry_after,
        )

    correlation_id: UUID = request.state.correlation_id
    return UsageService(db).get_current(principal, correlation_id=correlation_id, period=month)


@router.get("/usage/trends", response_model=UsageTrendResponse)
def get_usage_trends(
    granularity: Granularity = Query("day"),
    start: datetime | None = Query(None, description="Inclusive ISO-8601 start (default: 30 days before end)."),
    end: datetime | None = Query(None, description="Exclusive ISO-8601 end (default: now)."),
    types: str | None = Query(None, description="Comma-separated usage types (default: all metered types)."),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> UsageTrendResponse:
    """XR-F-07: usage summarized by period and usage type for the caller's tenant."""
    principal.require_scope("usage:read")
    retry_after = usage_limiter.check(principal.limiter_subject)
    if retry_after is not None:
        raise ApiError(429, "rate_limit_exceeded", "Usage read limit exceeded", retryable=True, retry_after_seconds=retry_after)
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(days=30)
    selected = [t.strip() for t in types.split(",") if t.strip()] if types else None
    return UsageTrendResponse.model_validate(usage_trend(db, principal.tenant_id, start=start, end=end,
                                                         granularity=granularity, usage_types=selected))
