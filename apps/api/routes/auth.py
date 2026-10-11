from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from graphrec_core.auth.audit import protected_auth_hash
from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.auth.service import AuthenticationService
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.registration.rate_limit import SharedRateLimiter
from graphrec_core.schemas.auth import (
    AuthTokenPair,
    LoginRequest,
    RecoverPasswordRequest,
    RecoverPasswordResponse,
    RefreshRequest,
    SetupPasswordRequest,
)
from graphrec_core.settings import Settings, get_settings

router = APIRouter(prefix="/v1/auth", tags=["authentication"])
settings = get_settings()
login_limiter = SharedRateLimiter(
    name="login",
    limit=settings.login_rate_limit,
    window_seconds=settings.login_rate_window_seconds,
)
# Setup tokens are unguessable, but the public endpoint still needs a per-source
# ceiling so it cannot be used to probe tokens or burn password-hashing CPU.
setup_limiter = SharedRateLimiter(
    name="setup",
    limit=settings.login_rate_limit,
    window_seconds=settings.login_rate_window_seconds,
)
refresh_limiter = SharedRateLimiter(
    name="refresh",
    limit=max(settings.login_rate_limit * 4, 30),
    window_seconds=settings.login_rate_window_seconds,
)
recovery_limiter = SharedRateLimiter(
    name="recovery",
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

    retry_after = setup_limiter.check(f"source:{source}")
    if retry_after is not None:
        service.record_setup_rate_limit_denial(
            correlation_id=correlation_id,
            source=source,
            retry_after_seconds=retry_after,
        )
        raise ApiError(
            429,
            "rate_limit_exceeded",
            "Account setup request limit exceeded",
            retryable=True,
            retry_after_seconds=retry_after,
        )

    return service.setup_password(
        payload,
        correlation_id=correlation_id,
        source=source,
    )


@router.post("/recover-password", response_model=RecoverPasswordResponse)
def recover_password(
    payload: RecoverPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    app_settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    source = request.client.host if request.client else "unknown"
    retry_after = recovery_limiter.check(f"source:{source}")
    service = AuthenticationService(db, app_settings)
    if retry_after is not None:
        service._record_recovery_denial(request.state.correlation_id, source, None)
        db.commit()
        raise ApiError(429, "rate_limit_exceeded", "Account recovery request limit exceeded",
                       retryable=True, retry_after_seconds=retry_after)
    service.recover_password(payload, correlation_id=request.state.correlation_id, source=source)
    return {"status": "completed"}


@router.post("/refresh", response_model=AuthTokenPair)
def refresh_session(
    payload: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
    app_settings: Settings = Depends(get_settings),
) -> AuthTokenPair:
    """Exchange a refresh token for a new token pair (A-05).

    Each refresh token works once and is replaced by the one returned here. The
    sign-in's absolute lifetime is not extended. Presenting a token that was
    already rotated signs the user out everywhere.
    """
    source = request.client.host if request.client else "unknown"
    retry_after = refresh_limiter.check(f"source:{source}")
    if retry_after is not None:
        raise ApiError(429, "rate_limit_exceeded", "Session refresh limit exceeded",
                       retryable=True, retry_after_seconds=retry_after)
    return AuthenticationService(db, app_settings).refresh(
        payload.refresh_token, correlation_id=request.state.correlation_id, source=source,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
    app_settings: Settings = Depends(get_settings),
) -> Response:
    """End the caller's sessions: every access token for this user stops working
    immediately (auth epoch bump) and all refresh sessions are revoked."""
    principal.require_bearer()
    AuthenticationService(db, app_settings).logout(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        correlation_id=request.state.correlation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
