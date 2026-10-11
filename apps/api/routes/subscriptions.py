from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.registration.rate_limit import SharedRateLimiter
from graphrec_core.schemas.plan_requests import (
    PlanChangeRequestCreate,
    PlanChangeRequestList,
    PlanChangeRequestResource,
)
from graphrec_core.schemas.subscription import SubscriptionResponse
from graphrec_core.settings import get_settings
from graphrec_core.subscription.requests import PlanRequestService
from graphrec_core.subscription.service import SubscriptionService

router = APIRouter(prefix="/v1", tags=["subscription"])
settings = get_settings()
subscription_limiter = SharedRateLimiter(
    name="subscription",
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


# -- plan change requests (migration 0039) ---------------------------------------------
# GraphRec takes no payments: a tenant administrator asks for a plan, a platform
# operator approves it, and approval activates the plan.

@router.get("/subscription/requests", response_model=PlanChangeRequestList)
def list_plan_requests(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> PlanChangeRequestList:
    principal.require_scope("billing:read")
    return PlanRequestService(db, principal, request.state.correlation_id).list()


@router.post("/subscription/requests", response_model=PlanChangeRequestResource, status_code=201)
def create_plan_request(
    payload: PlanChangeRequestCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> PlanChangeRequestResource:
    principal.require_scope("billing:write")
    return PlanRequestService(db, principal, request.state.correlation_id).create(payload)


@router.post("/subscription/requests/{request_id}:cancel", response_model=PlanChangeRequestResource)
def cancel_plan_request(
    request_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> PlanChangeRequestResource:
    principal.require_scope("billing:write")
    return PlanRequestService(db, principal, request.state.correlation_id).cancel(request_id)
