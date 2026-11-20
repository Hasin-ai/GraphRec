"""Tenant user administration: a tenant administrator invites developers and
other administrators (NR-F-02, SRS 2.7 "configures authorized users").

An invitation creates an ``invited`` user without a credential and stages a
one-time setup token, exactly as tenant registration does for the first
administrator. The token is returned once and never stored in clear.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from graphrec_core.auth.audit import protected_auth_hash
from graphrec_core.auth.principal import AuthenticatedPrincipal
from graphrec_core.auth.setup_tokens import issue_setup_token, revoke_open_setup_tokens
from graphrec_core.database.models import AuditLog, RefreshSession, TenantUser
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.schemas.tenant_users import (
    TenantUserInvite,
    TenantUserInviteResponse,
    TenantUserListResponse,
    TenantUserResource,
    TenantUserUpdate,
)
from graphrec_core.settings import Settings

MAX_USERS_PER_TENANT = 50


def require_tenant_administrator(principal: AuthenticatedPrincipal) -> None:
    """Only a signed-in tenant administrator manages users; API keys never do."""
    principal.require_bearer()
    principal.require_scope("users:write")
    if principal.role != "tenant_administrator":
        raise ApiError(403, "insufficient_role", "Only a tenant administrator can manage users")


def email_in_use(session: Session, email: str) -> bool:
    """True when any tenant has a user (other than a revoked invitation) with this email."""
    rows = session.execute(text(
        "SELECT user_status FROM resolve_login_identities(:email)"), {"email": email}).all()
    return any(row.user_status != "disabled" for row in rows)


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
        # D12: sign-in resolves users by email across tenants, so an email that
        # already belongs to a user anywhere cannot be invited again (same rule
        # as tenant registration). The message does not say where it exists.
        if email_in_use(self.session, payload.email):
            raise ApiError(409, "duplicate_resource",
                           "This email address cannot be invited. Ask the person for a different address.")
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

    def update_user(self, principal: AuthenticatedPrincipal, user_id: UUID, payload: "TenantUserUpdate", *,
                    correlation_id: UUID) -> TenantUserResource:
        """Change a member's role or status. Any change ends the member's sessions.

        Rules: administrators cannot change their own role or status, a tenant keeps at
        least one active administrator, invitations are managed with resend/revoke, and
        a disabled account stays disabled.
        """
        require_tenant_administrator(principal)
        if payload.role is None and payload.status is None:
            raise ApiError(422, "validation_failed", "Provide a role or a status.")
        if principal.user_id == user_id:
            raise ApiError(409, "invalid_state", "You cannot change your own role or access. Ask another administrator.")
        now = datetime.now(timezone.utc)
        set_local_tenant(self.session, principal.tenant_id)
        if payload.reason:
            from graphrec_core.database.tenancy import set_audit_reason
            set_audit_reason(self.session, payload.reason)
        # One member change per tenant at a time: keeps the last-administrator rule
        # race-free without row-lock ordering (and so without deadlocks).
        self.session.execute(text("SELECT pg_advisory_xact_lock(hashtext('tenant_members:' || :tenant))"),
                             {"tenant": str(principal.tenant_id)})
        user = self.session.scalar(select(TenantUser).where(
            TenantUser.tenant_id == principal.tenant_id, TenantUser.id == user_id).with_for_update())
        if user is None:
            raise ApiError(404, "resource_not_found", "User not found.")
        if user.status == "invited":
            raise ApiError(409, "invalid_state", "This is a pending invitation. Resend or revoke it instead.")
        if user.status == "disabled" and payload.status != "disabled":
            raise ApiError(409, "invalid_state", "A disabled account cannot be re-enabled. Invite the person again.")
        changes: dict[str, object] = {}
        if payload.role is not None and payload.role != user.role:
            changes["role"] = payload.role
        if payload.status is not None and payload.status != user.status:
            changes["status"] = payload.status
        if not changes:
            return TenantUserResource.model_validate(user)
        losing_admin = user.role == "tenant_administrator" and user.status == "active" and (
            changes.get("role", user.role) != "tenant_administrator" or changes.get("status", "active") != "active")
        if losing_admin:
            # Lock every active administrator row so two concurrent demotions cannot
            # both see two administrators and leave the tenant with none.
            admins = len(self.session.scalars(select(TenantUser.id).where(
                TenantUser.tenant_id == principal.tenant_id, TenantUser.role == "tenant_administrator",
                TenantUser.status == "active").order_by(TenantUser.id).with_for_update()).all())
            if admins <= 1:
                raise ApiError(409, "invalid_state", "A tenant must keep at least one active administrator.")
        self.session.execute(update(TenantUser).where(
            TenantUser.tenant_id == principal.tenant_id, TenantUser.id == user.id,
        ).values(**changes, auth_epoch=TenantUser.auth_epoch + 1))
        self.session.execute(update(RefreshSession).where(
            RefreshSession.tenant_id == principal.tenant_id, RefreshSession.user_id == user.id,
            RefreshSession.revoked_at.is_(None)).values(revoked_at=now))
        self.session.add(AuditLog(
            id=uuid4(), tenant_id=principal.tenant_id, actor_type=principal.actor_type,
            actor_reference=principal.actor_reference, action_type="tenant_user_updated",
            resource_type="tenant_user", resource_reference=user.id, outcome="succeeded",
            correlation_reference=correlation_id,
            redacted_details={k: str(v) for k, v in changes.items()}, occurred_at=now))
        self.session.commit()
        set_local_tenant(self.session, principal.tenant_id)
        self.session.refresh(user)
        return TenantUserResource.model_validate(user)

    def resend_invitation(self, principal: AuthenticatedPrincipal, user_id: UUID, *,
                          correlation_id: UUID) -> TenantUserInviteResponse:
        """Issue a fresh one-time setup link for a pending invitation; earlier links stop working."""
        require_tenant_administrator(principal)
        now = datetime.now(timezone.utc)
        set_local_tenant(self.session, principal.tenant_id)
        user = self.session.scalar(select(TenantUser).where(
            TenantUser.tenant_id == principal.tenant_id, TenantUser.id == user_id).with_for_update())
        if user is None:
            raise ApiError(404, "resource_not_found", "User not found.")
        if user.status != "invited":
            raise ApiError(409, "invalid_state", "Only a pending invitation can be resent.")
        revoke_open_setup_tokens(self.session, tenant_id=principal.tenant_id, user_id=user.id, now=now)
        token, expires_at = issue_setup_token(self.session, tenant_id=principal.tenant_id, user_id=user.id,
                                              ttl_seconds=self.settings.account_setup_token_ttl_seconds, now=now)
        self.session.add(AuditLog(
            id=uuid4(), tenant_id=principal.tenant_id, actor_type=principal.actor_type,
            actor_reference=principal.actor_reference, action_type="tenant_user_invitation_resent",
            resource_type="tenant_user", resource_reference=user.id, outcome="succeeded",
            correlation_reference=correlation_id, redacted_details={}, occurred_at=now))
        self.session.commit()
        set_local_tenant(self.session, principal.tenant_id)
        self.session.refresh(user)
        return TenantUserInviteResponse(**TenantUserResource.model_validate(user).model_dump(),
                                        setup_token=token, setup_token_expires_at=expires_at)

    def revoke_invitation(
        self, principal: AuthenticatedPrincipal, user_id: UUID, *, correlation_id: UUID
    ) -> TenantUserResource:
        """Withdraw a pending invitation: the user is disabled and its setup links stop working."""
        require_tenant_administrator(principal)
        now = datetime.now(timezone.utc)
        set_local_tenant(self.session, principal.tenant_id)
        user = self.session.scalar(select(TenantUser).where(
            TenantUser.tenant_id == principal.tenant_id, TenantUser.id == user_id).with_for_update())
        if user is None:
            raise ApiError(404, "resource_not_found", "User not found.")
        if user.status != "invited":
            raise ApiError(409, "invalid_state", "Only a pending invitation can be revoked.")
        revoke_open_setup_tokens(self.session, tenant_id=principal.tenant_id, user_id=user.id, now=now)
        self.session.execute(update(TenantUser).where(
            TenantUser.tenant_id == principal.tenant_id, TenantUser.id == user.id,
            TenantUser.status == "invited").values(status="disabled"))
        self.session.add(AuditLog(
            id=uuid4(), tenant_id=principal.tenant_id, actor_type=principal.actor_type,
            actor_reference=principal.actor_reference, action_type="tenant_user_invitation_revoked",
            resource_type="tenant_user", resource_reference=user.id, outcome="succeeded",
            correlation_reference=correlation_id, redacted_details={}, occurred_at=now))
        self.session.commit()
        set_local_tenant(self.session, principal.tenant_id)
        self.session.refresh(user)
        return TenantUserResource.model_validate(user)
