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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.control_api.deps import (
    CurrentTenant,
    RequireAdministrator,
    TenantAudit,
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
from graphrec.common.enums import AuditAction, TenantRole, UserStatus
from graphrec.common.errors import NotFoundError
from graphrec.db.models import TenantUser
from graphrec.domain.identity import IdentityService

router = APIRouter(prefix="/users", tags=["users"])


def _service(
    tokens: Annotated[TokenService, Depends(get_token_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> IdentityService:
    return IdentityService(tokens, invitation_ttl_seconds=settings.invitation_ttl_seconds)


Service = Annotated[IdentityService, Depends(_service)]


async def _active_administrators(session: AsyncSession) -> int:
    """How many active administrators this tenant has. RLS supplies the tenant.

    One query serves a whole page, rather than one per row: the count does not
    depend on which user is being rendered, only on whether *that* user is one
    of the ones counted.
    """
    total = await session.scalar(
        select(func.count())
        .select_from(TenantUser)
        .where(
            TenantUser.role == TenantRole.TENANT_ADMINISTRATOR.value,
            TenantUser.status == UserStatus.ACTIVE.value,
        )
    )
    return total or 0


def _render(user: TenantUser, *, active_administrators: int) -> UserResponse:
    """No `credential_digest`, and no `tenant_id`. Neither belongs in a response.

    The last-administrator flag is deliberately *not* "this user is an
    administrator and the count is 1" alone — an administrator who is already
    disabled is not holding the tenant open, so demoting them is safe and the
    control should not be disabled. The condition is the same one
    `IdentityService._refuse_if_last_administrator` enforces, which is why both
    read `role` and `status` rather than `role` alone; if they ever disagree the
    console offers a button the server refuses, which is the failure §10.4 calls
    out by name.
    """
    is_last = (
        user.role == TenantRole.TENANT_ADMINISTRATOR.value
        and user.status == UserStatus.ACTIVE.value
        and active_administrators <= 1
    )
    return UserResponse(
        tenant_user_id=user.tenant_user_id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        last_authenticated_at=user.last_authenticated_at,
        is_last_active_administrator=is_last,
    )


@router.get("", response_model=UserListResponse, summary="Users in the caller's tenant")
async def list_users(principal: CurrentTenant) -> UserListResponse:
    """No `WHERE tenant_id` clause, and none needed: RLS supplies it."""
    rows = (
        await principal.session.scalars(select(TenantUser).order_by(TenantUser.created_at))
    ).all()
    administrators = await _active_administrators(principal.session)
    # `total` equals the page here because this list is not paginated: a tenant's
    # user count is bounded by how many people work there. The field exists
    # anyway because §10.9 requires every table to be able to render "N of M",
    # and a list that grows a `limit` later should not also have to grow a field.
    return UserListResponse(
        users=[_render(user, active_administrators=administrators) for user in rows],
        total=len(rows),
    )


@router.get("/{tenant_user_id}", response_model=UserResponse, summary="One user in the tenant")
async def get_user(tenant_user_id: uuid.UUID, principal: CurrentTenant) -> UserResponse:
    """`/users/:userId` reads this. Open to both roles, exactly as the list is.

    No `tenant_id` predicate: the session is bound, so another tenant's user
    returns no row and becomes a 404 — the same answer an identifier belonging
    to nobody gets. That equality is the point (§13), and adding a predicate
    here would eventually turn one of those into a 403.
    """
    user = await principal.session.scalar(
        select(TenantUser).where(TenantUser.tenant_user_id == tenant_user_id)
    )
    if user is None:
        raise NotFoundError()
    administrators = await _active_administrators(principal.session)
    return _render(user, active_administrators=administrators)


@router.post(
    "",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user to the caller's tenant",
)
async def create_user(
    body: CreateUserRequest,
    principal: RequireAdministrator,
    service: Service,
    audit: TenantAudit,
) -> InvitationResponse:
    """Creates an `invited` user and the token that activates it.

    `invited_by` is the principal's own id, taken from the verified token. There
    is no body field for it, because an administrator being able to record
    somebody else as the inviter would make the audit trail a fiction.
    """
    async with audit.action(AuditAction.ACCESS, resource_type="tenant_user") as entry:
        issued = await service.create_user(
            principal.session,
            tenant_id=principal.tenant_id,
            email=body.email,
            display_name=body.display_name,
            role=body.role.value,
            invited_by=principal.user_id,
        )
        entry.resource_ref = issued.user.tenant_user_id
        # The role, not the address. The invited user's email is their personal
        # data and the row is readable by every administrator the tenant ever
        # has; the id identifies them precisely and the users page resolves it.
        entry.details = {"operation": "invite", "role": body.role.value}
    return InvitationResponse(
        user=_render(
            issued.user, active_administrators=await _active_administrators(principal.session)
        ),
        invitation_id=issued.invitation.invitation_id,
        expires_at=issued.invitation.expires_at,
        invitation_token=issued.token,
    )


@router.post(
    "/{tenant_user_id}:resend-invitation",
    response_model=InvitationResponse,
    summary="Issue a fresh invitation to a user who has not accepted",
)
async def resend_invitation(
    tenant_user_id: uuid.UUID,
    principal: RequireAdministrator,
    service: Service,
    audit: TenantAudit,
) -> InvitationResponse:
    """`/users/:userId`'s Resend invitation dialog.

    A colon verb rather than `PUT /invitations/{id}`, because this does not
    replace a resource the caller can name — the caller names the *user*, and
    which invitation row exists for them is the server's business. It refuses
    with 409 `user_not_invited` for anyone already active, locked or disabled.
    """
    async with audit.action(
        AuditAction.ACCESS,
        resource_type="tenant_user",
        resource_ref=tenant_user_id,
        details={"operation": "resend_invitation"},
    ):
        issued = await service.reissue_invitation(
            principal.session,
            tenant_id=principal.tenant_id,
            target_user_id=tenant_user_id,
        )
    return InvitationResponse(
        user=_render(
            issued.user, active_administrators=await _active_administrators(principal.session)
        ),
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
    audit: TenantAudit,
) -> UserResponse:
    """May refuse with 409 `last_active_administrator` — see the service.

    That refusal is audited too, as `cancelled`: an administrator who tried to
    demote the last administrator and was stopped is a thing worth being able to
    see afterwards, and it is exactly the row that the refusal's own rollback
    would have destroyed had it been written on this transaction.
    """
    async with audit.action(
        AuditAction.ACCESS,
        resource_type="tenant_user",
        resource_ref=tenant_user_id,
        details={"operation": "change_role", "role": body.role.value},
    ):
        user = await service.change_user_role(
            principal.session,
            tenant_id=principal.tenant_id,
            target_user_id=tenant_user_id,
            new_role=body.role.value,
        )
    return _render(user, active_administrators=await _active_administrators(principal.session))


@router.patch("/{tenant_user_id}/status", response_model=UserResponse, summary="Change a status")
async def change_status(
    tenant_user_id: uuid.UUID,
    body: ChangeStatusRequest,
    principal: RequireAdministrator,
    service: Service,
    audit: TenantAudit,
) -> UserResponse:
    async with audit.action(
        AuditAction.ACCESS,
        resource_type="tenant_user",
        resource_ref=tenant_user_id,
        details={"operation": "change_status", "status": body.status.value},
    ):
        user = await service.set_user_status(
            principal.session,
            tenant_id=principal.tenant_id,
            target_user_id=tenant_user_id,
            new_status=body.status.value,
        )
    return _render(user, active_administrators=await _active_administrators(principal.session))
