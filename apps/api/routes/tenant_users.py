"""Tenant user administration (``/v1/tenant/users``)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.auth.users import TenantUserService
from graphrec_core.database.session import get_db
from graphrec_core.errors import ApiError
from graphrec_core.schemas.tenant_users import (
    TenantUserInvite,
    TenantUserInviteResponse,
    TenantUserListResponse,
    TenantUserResource,
    TenantUserUpdate,
)
from graphrec_core.settings import get_settings

router = APIRouter(prefix="/v1/tenant/users", tags=["tenant-users"])


@router.get("", response_model=TenantUserListResponse)
def list_tenant_users(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TenantUserListResponse:
    principal.require_bearer()
    principal.require_scope("users:write")
    return TenantUserService(db, get_settings()).list_users(principal)


@router.post("", response_model=TenantUserInviteResponse, status_code=status.HTTP_201_CREATED)
def invite_tenant_user(
    body: TenantUserInvite,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TenantUserInviteResponse:
    principal.require_bearer()
    principal.require_scope("users:write")
    return TenantUserService(db, get_settings()).invite_user(
        principal, body, correlation_id=request.state.correlation_id
    )


@router.delete("/{user_id}/invitation", response_model=TenantUserResource)
def revoke_tenant_user_invitation(
    user_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TenantUserResource:
    """Withdraw a pending invitation; its one-time setup link stops working."""
    principal.require_bearer()
    principal.require_scope("users:write")
    return TenantUserService(db, get_settings()).revoke_invitation(
        principal, user_id, correlation_id=request.state.correlation_id
    )


@router.get("/{user_id}", response_model=TenantUserResource)
def get_tenant_user(
    user_id: UUID,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TenantUserResource:
    principal.require_bearer()
    principal.require_scope("users:write")
    for user in TenantUserService(db, get_settings()).list_users(principal).items:
        if user.id == user_id:
            return user
    raise ApiError(404, "resource_not_found", "User not found.")


@router.patch("/{user_id}", response_model=TenantUserResource)
def update_tenant_user(
    user_id: UUID,
    body: TenantUserUpdate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TenantUserResource:
    """Change a member's role, or lock, unlock or disable the account. Ends the member's sessions."""
    principal.require_bearer()
    principal.require_scope("users:write")
    return TenantUserService(db, get_settings()).update_user(
        principal, user_id, body, correlation_id=request.state.correlation_id)


@router.post("/{user_id}/invitation:resend", response_model=TenantUserInviteResponse)
def resend_tenant_user_invitation(
    user_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TenantUserInviteResponse:
    """Issue a new one-time setup link for a pending invitation; earlier links stop working."""
    principal.require_bearer()
    principal.require_scope("users:write")
    return TenantUserService(db, get_settings()).resend_invitation(
        principal, user_id, correlation_id=request.state.correlation_id)
