"""Tenant user administration: a tenant administrator invites developers and
other administrators (NR-F-02, SRS 2.7 "configures authorized users").

An invitation creates an ``invited`` user without a credential and stages a
one-time setup token, exactly as tenant registration does for the first
administrator. The token is returned once and never stored in clear.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from graphrec_core.auth.audit import protected_auth_hash
from graphrec_core.auth.principal import AuthenticatedPrincipal
from graphrec_core.auth.setup_tokens import issue_setup_token
from graphrec_core.database.models import AuditLog, TenantUser
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.schemas.tenant_users import (
    TenantUserInvite,
    TenantUserInviteResponse,
    TenantUserListResponse,
    TenantUserResource,
)
from graphrec_core.settings import Settings

MAX_USERS_PER_TENANT = 50


def require_tenant_administrator(principal: AuthenticatedPrincipal) -> None:
    """Only a signed-in tenant administrator manages users; API keys never do."""
    principal.require_bearer()
    principal.require_scope("users:write")
    if principal.role != "tenant_administrator":
        raise ApiError(403, "insufficient_role", "Only a tenant administrator can manage users")


class TenantUserService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings

    def list_users(self, principal: AuthenticatedPrincipal) -> TenantUserListResponse:
        require_tenant_administrator(principal)
        set_local_tenant(self.session, principal.tenant_id)
        rows = (
            self.session.execute(
                select(TenantUser)
                .where(TenantUser.tenant_id == principal.tenant_id)
                .order_by(TenantUser.created_at.asc(), TenantUser.email.asc())
            )
            .scalars()
            .all()
        )
        items = [TenantUserResource.model_validate(row) for row in rows]
        return TenantUserListResponse(items=items, total=len(items))

    def invite_user(
        self, principal: AuthenticatedPrincipal, payload: TenantUserInvite, *, correlation_id: UUID
    ) -> TenantUserInviteResponse:
        require_tenant_administrator(principal)
        now = datetime.now(timezone.utc)
        set_local_tenant(self.session, principal.tenant_id)

        existing = self.session.scalar(
            select(TenantUser).where(
                TenantUser.tenant_id == principal.tenant_id,
                TenantUser.email == payload.email,
            )
        )
        if existing is not None:
            raise ApiError(409, "duplicate_resource", "A user with this email already exists in the tenant")
        count = self.session.scalar(
            select(func.count(TenantUser.id)).where(TenantUser.tenant_id == principal.tenant_id)
        )
        if count is not None and count >= MAX_USERS_PER_TENANT:
            raise ApiError(409, "limit_exceeded", f"A tenant may have at most {MAX_USERS_PER_TENANT} users")

        user = TenantUser(
            id=uuid4(),
            tenant_id=principal.tenant_id,
            email=payload.email,
            display_name=payload.display_name or payload.email.split("@", 1)[0],
            credential_digest=None,
            role=payload.role,
            status="invited",
            created_at=now,
            last_authenticated_at=None,
        )
        self.session.add(user)
        self.session.flush()
        token, expires_at = issue_setup_token(
            self.session,
            tenant_id=principal.tenant_id,
            user_id=user.id,
            ttl_seconds=self.settings.account_setup_token_ttl_seconds,
            now=now,
        )
        self.session.add(
            AuditLog(
                id=uuid4(),
                tenant_id=principal.tenant_id,
                actor_type=principal.actor_type,
                actor_reference=principal.actor_reference,
                action_type="tenant_user_invited",
                resource_type="tenant_user",
                resource_reference=user.id,
                outcome="succeeded",
                correlation_reference=correlation_id,
                redacted_details={
                    "role": payload.role,
                    "email_hash": protected_auth_hash(payload.email),
                },
                occurred_at=now,
            )
        )
        self.session.commit()
        return TenantUserInviteResponse(
            **TenantUserResource.model_validate(user).model_dump(),
            setup_token=token,
            setup_token_expires_at=expires_at,
        )
