from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from graphrec_core.api_keys.service import ApiKeyService
from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.registration.rate_limit import RegistrationRateLimiter
from graphrec_core.schemas.api_keys import (
    ApiKeyCreateRequest,
    ApiKeyListResponse,
    ApiKeyResponse,
    ApiKeyRotateRequest,
    ApiKeySecretResponse,
)
from graphrec_core.settings import get_settings

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])
settings = get_settings()
api_key_limiter = RegistrationRateLimiter(
    limit=settings.api_key_rate_limit,
    window_seconds=settings.api_key_rate_window_seconds,
)


def _authorize(request: Request, principal: AuthenticatedPrincipal) -> None:
    principal.require_bearer()
    principal.require_scope("keys:write")
    if request.query_params:
        raise ApiError(
            422,
            "validation_failed",
            "API-key lifecycle endpoints do not accept query parameters",
            details={
                "fields": [
                    {"field": key, "message": "Unexpected query parameter"}
                    for key in sorted(request.query_params.keys())
                ]
            },
        )
    retry_after = api_key_limiter.check(principal.limiter_subject)
    if retry_after is not None:
        raise ApiError(
            429,
            "rate_limit_exceeded",
            "API-key administrative rate limit exceeded",
            retryable=True,
            retry_after_seconds=retry_after,
        )


@router.get("", response_model=ApiKeyListResponse)
def list_api_keys(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ApiKeyListResponse:
    _authorize(request, principal)
    return ApiKeyService(db, settings).list_keys(
        principal, correlation_id=request.state.correlation_id
    )


@router.get("/{key_id}", response_model=ApiKeyResponse)
def get_api_key(
    key_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ApiKeyResponse:
    _authorize(request, principal)
    return ApiKeyService(db, settings).get_key(
        principal, key_id, correlation_id=request.state.correlation_id
    )


@router.post("", response_model=ApiKeySecretResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: ApiKeyCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ApiKeySecretResponse:
    _authorize(request, principal)
    return ApiKeyService(db, settings).create_key(
        principal, body, correlation_id=request.state.correlation_id
    )


@router.post("/{key_id}/rotate", response_model=ApiKeySecretResponse)
def rotate_api_key(
    key_id: UUID,
    body: ApiKeyRotateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ApiKeySecretResponse:
    _authorize(request, principal)
    return ApiKeyService(db, settings).rotate_key(
        principal, key_id, body, correlation_id=request.state.correlation_id
    )


@router.delete("/{key_id}", response_model=ApiKeyResponse)
def revoke_api_key(
    key_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ApiKeyResponse:
    _authorize(request, principal)
    return ApiKeyService(db, settings).revoke_key(
        principal, key_id, correlation_id=request.state.correlation_id
    )
