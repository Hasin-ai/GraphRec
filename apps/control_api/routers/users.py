"""Tenant user administration.

Read is open to both roles — a developer seeing who else is in their own tenant
is not a leak — while every mutation depends on `RequireAdministrator`, which
runs gate 3 after gates 1 and 2.

No handler here filters by `tenant_id`. The principal's session is already bound,
so a foreign identifier returns no row and becomes a 404 (gate 4). A
`WHERE tenant_id = ...` added "for safety" would be a second copy of a check the
database already makes, and the copy is what drifts.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from apps.control_api.deps import (
    CurrentTenant,
    RequireAdministrator,
    get_settings_dep,
    get_token_service,
)
from apps.control_api.schemas import (
    ChangeRoleRequest,
    ChangeStatusRequest,
    CreateUserRequest,
    InvitationResponse,
    UserListResponse,
    UserResponse,
)
from graphrec.auth.tokens import TokenService
from graphrec.common.config import Settings
from graphrec.db.models import TenantUser
from graphrec.domain.identity import IdentityService

router = APIRouter(prefix="/users", tags=["users"])


def _service(
    tokens: Annotated[TokenService, Depends(get_token_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> IdentityService:
    return IdentityService(tokens, invitation_ttl_seconds=settings.invitation_ttl_seconds)


Service = Annotated[IdentityService, Depends(_service)]


def _render(user: TenantUser) -> UserResponse:
    """No `credential_digest`, and no `tenant_id`. Neither belongs in a response."""
    return UserResponse(
        tenant_user_id=user.tenant_user_id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        last_authenticated_at=user.last_authenticated_at,
    )


@router.get("", response_model=UserListResponse, summary="Users in the caller's tenant")
async def list_users(principal: CurrentTenant) -> UserListResponse:
    """No `WHERE tenant_id` clause, and none needed: RLS supplies it."""
    rows = await principal.session.scalars(select(TenantUser).order_by(TenantUser.created_at))
    return UserListResponse(users=[_render(user) for user in rows])


@router.post(
    "",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user to the caller's tenant",
)
async def create_user(
    body: CreateUserRequest, principal: RequireAdministrator, service: Service
) -> InvitationResponse:
    """Creates an `invited` user and the token that activates it.

    `invited_by` is the principal's own id, taken from the verified token. There
    is no body field for it, because an administrator being able to record
    somebody else as the inviter would make the audit trail a fiction.
    """
    issued = await service.create_user(
        principal.session,
        tenant_id=principal.tenant_id,
        email=body.email,
        display_name=body.display_name,
        role=body.role.value,
        invited_by=principal.user_id,
    )
    return InvitationResponse(
        user=_render(issued.user),
        invitation_id=issued.invitation.invitation_id,
        expires_at=issued.invitation.expires_at,
        invitation_token=issued.token,
    )


@router.patch("/{tenant_user_id}/role", response_model=UserResponse, summary="Change a role")
async def change_role(
    tenant_user_id: uuid.UUID,
    body: ChangeRoleRequest,
    principal: RequireAdministrator,
    service: Service,
) -> UserResponse:
    """May refuse with 409 `last_active_administrator` — see the service."""
    user = await service.change_user_role(
        principal.session,
        tenant_id=principal.tenant_id,
        target_user_id=tenant_user_id,
        new_role=body.role.value,
    )
    return _render(user)


@router.patch("/{tenant_user_id}/status", response_model=UserResponse, summary="Change a status")
async def change_status(
    tenant_user_id: uuid.UUID,
    body: ChangeStatusRequest,
    principal: RequireAdministrator,
    service: Service,
) -> UserResponse:
    user = await service.set_user_status(
        principal.session,
        tenant_id=principal.tenant_id,
        target_user_id=tenant_user_id,
        new_status=body.status.value,
    )
    return _render(user)
