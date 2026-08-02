from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.registration.rate_limit import RegistrationRateLimiter
from graphrec_core.schemas.usage import UsageSummaryResponse
from graphrec_core.settings import get_settings
from graphrec_core.usage.service import UsageService

router = APIRouter(prefix="/v1", tags=["usage"])
settings = get_settings()
usage_limiter = RegistrationRateLimiter(
    limit=settings.usage_rate_limit,
    window_seconds=settings.usage_rate_window_seconds,
)


@router.get("/usage", response_model=UsageSummaryResponse)
def get_usage(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> UsageSummaryResponse:
    principal.require_scope("usage:read")
    if request.query_params:
        raise ApiError(
            422,
            "validation_failed",
            "This endpoint does not accept query parameters",
            details={
                "fields": [
                    {"field": key, "message": "Unexpected query parameter"}
                    for key in sorted(request.query_params.keys())
                ]
            },
        )

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
    return UsageService(db).get_current(principal, correlation_id=correlation_id)
