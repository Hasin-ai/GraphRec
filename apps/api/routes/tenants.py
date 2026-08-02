from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.registration.rate_limit import RegistrationRateLimiter
from graphrec_core.registration.service import RegistrationService
from graphrec_core.schemas.registration import (
    TenantRegistrationRequest,
    TenantRegistrationResponse,
)
from graphrec_core.settings import Settings, get_settings

router = APIRouter(prefix="/v1", tags=["tenants"])
settings = get_settings()
registration_limiter = RegistrationRateLimiter(
    limit=settings.registration_rate_limit,
    window_seconds=settings.registration_rate_window_seconds,
)


@router.post(
    "/tenants",
    response_model=TenantRegistrationResponse,
    status_code=201,
    responses={200: {"model": TenantRegistrationResponse}},
)
def register_tenant(
    payload: TenantRegistrationRequest,
    request: Request,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    app_settings: Settings = Depends(get_settings),
) -> TenantRegistrationResponse:
    normalized_key = idempotency_key.strip()
    if not normalized_key or len(normalized_key) > app_settings.max_idempotency_key_length:
        raise ApiError(
            422,
            "validation_failed",
            "Idempotency-Key must be a non-empty bounded value",
            details={"fields": [{"field": "Idempotency-Key", "message": "Invalid value"}]},
        )

    source = request.client.host if request.client else "unknown"
    correlation_id: UUID = request.state.correlation_id
    service = RegistrationService(db, app_settings)
    retry_after = registration_limiter.check(source)
    if retry_after is not None:
        service.record_rate_limit_denial(
            correlation_id=correlation_id,
            source=source,
            retry_after_seconds=retry_after,
        )
        raise ApiError(
            429,
            "rate_limit_exceeded",
            "Registration request limit exceeded",
            retryable=True,
            retry_after_seconds=retry_after,
            details={"limit_name": "tenant_registration_attempts"},
        )

    result = service.register(
        payload,
        idempotency_key=normalized_key,
        correlation_id=correlation_id,
        source=source,
    )
    response.status_code = 200 if result.replayed else 201
    return result.response
