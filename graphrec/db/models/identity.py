"""Tenants, users and the credentials that authenticate them.

Two realms live here and are deliberately kept apart. `TenantUser` belongs to
exactly one tenant and carries a role; `PlatformUser` belongs to no tenant and
carries named permissions. Nothing joins them, because no query should ever need
to treat an operator and a tenant member as interchangeable.

`credential_digest` is an Argon2id digest and never leaves the database. There is
no column anywhere holding a password, a token or a credential secret in a form
that can be read back.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from graphrec.common.enums import TenantRole, TenantStatus, UserStatus
from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column


class PricingPlan(Base):
    """Platform-owned, tenant-readable. Not tenant-scoped: plans are shared."""

    __tablename__ = "pricing_plans"

    plan_id: Mapped[uuid.UUID] = pk_uuid()
    plan_code: Mapped[str] = mapped_column(Text, unique=True)
    plan_name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    event_limit: Mapped[int] = mapped_column(BigInteger)
    recommendation_limit: Mapped[int] = mapped_column(BigInteger)
    training_limit: Mapped[int] = mapped_column(Integer)
    product_limit: Mapped[int] = mapped_column(BigInteger)
    storage_limit_bytes: Mapped[int] = mapped_column(BigInteger)
    service_limits: Mapped[dict[str, Any]] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()


class Tenant(Base):
    """The tenant itself. Its own `tenant_id` is what every policy compares to.

    `Tenant` does not mix in `TenantOwned`: the column it is scoped by is its
    primary key, not a foreign one. The policy is the same shape all the same,
    which is why a tenant cannot enumerate its neighbours.
    """

    __tablename__ = "tenants"

    tenant_id: Mapped[uuid.UUID] = pk_uuid()
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pricing_plans.plan_id"))
    tenant_code: Mapped[str] = mapped_column(Text, unique=True)
    tenant_name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default=TenantStatus.PENDING.value)
    settings: Mapped[dict[str, Any]] = mapped_column()
    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()
    status_changed_at: Mapped[dt.datetime | None] = mapped_column()
    status_reason: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[PricingPlan | None] = relationship(lazy="joined")

    @property
    def is_operable(self) -> bool:
        """Gate 2 — whether the tenant may act at all.

        Only `active` permits work. `pending`, `suspended`, `deleting` and
        `deleted` all refuse, and the prototype is explicit that the refusal is
        not something the tenant can act on: "The transition is controlled by a
        Platform Administrator; there is no tenant-side action that changes it."
        (dc.html L1059)
        """
        return self.status == TenantStatus.ACTIVE.value


class TenantUser(TenantOwned, Base):
    """A member of one tenant. Email is unique *per tenant*, not globally."""

    __tablename__ = "tenant_users"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)

    tenant_user_id: Mapped[uuid.UUID] = pk_uuid()
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    credential_digest: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default=UserStatus.INVITED.value)
    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()
    last_authenticated_at: Mapped[dt.datetime | None] = mapped_column()
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column()

    @property
    def is_administrator(self) -> bool:
        return self.role == TenantRole.TENANT_ADMINISTRATOR.value

    @property
    def can_authenticate(self) -> bool:
        """`active` only. `invited`, `locked` and `disabled` all refuse.

        All three refusals return the same sentence as a wrong password, because
        distinguishing them tells an attacker which emails exist and what state
        they are in.
        """
        return self.status == UserStatus.ACTIVE.value


class PlatformUser(Base):
    """An operator. Carries no `tenant_id`, and there is nowhere to put one."""

    __tablename__ = "platform_users"

    platform_user_id: Mapped[uuid.UUID] = pk_uuid()
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    credential_digest: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default=UserStatus.ACTIVE.value)
    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()
    last_authenticated_at: Mapped[dt.datetime | None] = mapped_column()
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column()

    permissions: Mapped[list[PlatformUserPermission]] = relationship(
        back_populates="platform_user",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    @property
    def can_authenticate(self) -> bool:
        return self.status == UserStatus.ACTIVE.value

    def granted(self) -> frozenset[str]:
        return frozenset(p.permission for p in self.permissions)


class PlatformUserPermission(Base):
    """One row per granted permission — the five are independently grantable.

    Modelled as rows rather than a bitmask or an array so that a grant carries
    who granted it and when, which the audit trail needs.
    """

    __tablename__ = "platform_user_permissions"

    platform_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_users.platform_user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission: Mapped[str] = mapped_column(Text, primary_key=True)
    granted_at: Mapped[dt.datetime] = utcnow_column()
    granted_by: Mapped[uuid.UUID | None] = mapped_column()

    platform_user: Mapped[PlatformUser] = relationship(back_populates="permissions")


class Invitation(TenantOwned, Base):
    """A pending membership. The token is stored as a digest, never in the clear."""

    __tablename__ = "invitations"

    invitation_id: Mapped[uuid.UUID] = pk_uuid()
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    token_digest: Mapped[str] = mapped_column(Text)
    invited_by: Mapped[uuid.UUID | None] = mapped_column()
    expires_at: Mapped[dt.datetime] = mapped_column()
    accepted_at: Mapped[dt.datetime | None] = mapped_column()
    revoked_at: Mapped[dt.datetime | None] = mapped_column()
    created_at: Mapped[dt.datetime] = utcnow_column()

    def is_open(self, now: dt.datetime) -> bool:
        return self.accepted_at is None and self.revoked_at is None and self.expires_at > now


class RefreshSession(Base):
    """One refresh credential. Exactly one of the two user columns is set.

    The table spans both realms, and the check constraint in migration 0002 makes
    the exclusivity structural: a tenant session has `tenant_user_id` and
    `tenant_id`; a platform session has `platform_user_id` and `tenant_id IS
    NULL`. A row that is somehow both cannot be written.

    `tenant_id` is nullable, so this class cannot use `TenantOwned` — but the
    table is still under RLS, and a platform row (`tenant_id IS NULL`) never
    matches a tenant policy.
    """

    __tablename__ = "refresh_sessions"

    refresh_session_id: Mapped[uuid.UUID] = pk_uuid()
    tenant_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenant_users.tenant_user_id", ondelete="CASCADE")
    )
    platform_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_users.platform_user_id", ondelete="CASCADE")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE")
    )
    token_digest: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column()
    revoked_at: Mapped[dt.datetime | None] = mapped_column()
    issued_at: Mapped[dt.datetime] = utcnow_column()
    last_used_at: Mapped[dt.datetime | None] = mapped_column()
    user_agent: Mapped[str | None] = mapped_column(Text)
    client_address: Mapped[str | None] = mapped_column(INET)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column()

    def is_usable(self, now: dt.datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now


class RecoveryToken(Base):
    """A single-use password-reset credential, stored as a digest.

    Same two-realm shape as `RefreshSession`, and the same reason for it.
    """

    __tablename__ = "recovery_tokens"

    recovery_token_id: Mapped[uuid.UUID] = pk_uuid()
    tenant_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenant_users.tenant_user_id", ondelete="CASCADE")
    )
    platform_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_users.platform_user_id", ondelete="CASCADE")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="CASCADE")
    )
    token_digest: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column()
    revoked_at: Mapped[dt.datetime | None] = mapped_column()
    created_at: Mapped[dt.datetime] = utcnow_column()
    consumed_at: Mapped[dt.datetime | None] = mapped_column()

    def is_usable(self, now: dt.datetime) -> bool:
        return self.consumed_at is None and self.revoked_at is None and self.expires_at > now
