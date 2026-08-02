from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.registration.rate_limit import RegistrationRateLimiter
from graphrec_core.schemas.subscription import SubscriptionResponse
from graphrec_core.settings import get_settings
from graphrec_core.subscription.service import SubscriptionService

router = APIRouter(prefix="/v1", tags=["subscription"])
settings = get_settings()
subscription_limiter = RegistrationRateLimiter(
    limit=settings.subscription_rate_limit,
    window_seconds=settings.subscription_rate_window_seconds,
)


@router.get("/subscription", response_model=SubscriptionResponse)
def get_subscription(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    principal.require_scope("billing:read")
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

    retry_after = subscription_limiter.check(principal.limiter_subject)
    if retry_after is not None:
        raise ApiError(
            429,
            "rate_limit_exceeded",
            "Subscription read limit exceeded",
            retryable=True,
            retry_after_seconds=retry_after,
        )

    correlation_id: UUID = request.state.correlation_id
    return SubscriptionService(db).get_current(
        principal,
        correlation_id=correlation_id,
    )
