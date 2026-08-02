from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from graphrec_core.auth.audit import protected_auth_hash
from graphrec_core.auth.service import AuthenticationService
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.registration.rate_limit import RegistrationRateLimiter
from graphrec_core.schemas.auth import AuthTokenPair, LoginRequest, SetupPasswordRequest
from graphrec_core.settings import Settings, get_settings

router = APIRouter(prefix="/v1/auth", tags=["authentication"])
settings = get_settings()
login_limiter = RegistrationRateLimiter(
    limit=settings.login_rate_limit,
    window_seconds=settings.login_rate_window_seconds,
)


@router.post("/login", response_model=AuthTokenPair)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    app_settings: Settings = Depends(get_settings),
) -> AuthTokenPair:
    source = request.client.host if request.client else "unknown"
    correlation_id: UUID = request.state.correlation_id
    service = AuthenticationService(db, app_settings)

    source_retry = login_limiter.check(f"source:{source}")
    account_retry = login_limiter.check(f"account:{protected_auth_hash(payload.email)}")
    retry_after = max(filter(None, [source_retry, account_retry]), default=None)
    if retry_after is not None:
        service.record_rate_limit_denial(
            email=payload.email,
            correlation_id=correlation_id,
            source=source,
            retry_after_seconds=retry_after,
        )
        raise ApiError(
            429,
            "rate_limit_exceeded",
            "Authentication request limit exceeded",
            retryable=True,
            retry_after_seconds=retry_after,
        )

    return service.login(
        payload,
        correlation_id=correlation_id,
        source=source,
    )


@router.post("/setup-password", response_model=AuthTokenPair)
def setup_password(
    payload: SetupPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    app_settings: Settings = Depends(get_settings),
) -> AuthTokenPair:
    source = request.client.host if request.client else "unknown"
    correlation_id: UUID = request.state.correlation_id
    service = AuthenticationService(db, app_settings)

    return service.setup_password(
        payload,
        correlation_id=correlation_id,
        source=source,
    )
