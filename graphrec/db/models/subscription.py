"""Plan assignment and the quota rows that meter a tenant against it.

Quotas exist in two layers, and the order matters. `TenantResourceQuota` holds
the effective limit for a usage type; `QuotaOverride` is a platform-granted
exception to it that carries a reason and may expire. Resolution is
override-first, plan-second, and the override's reason is written to the audit
history because it is a deliberate departure from what the tenant pays for.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column


class TenantSubscription(TenantOwned, Base):
    """One row per plan assignment, closed by `ended_at` rather than deleted.

    History is kept because a usage question about last month has to be answered
    against the plan that was in force then, not the one in force now.
    """

    __tablename__ = "tenant_subscriptions"

    subscription_id: Mapped[uuid.UUID] = pk_uuid()
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pricing_plans.plan_id"))
    started_at: Mapped[dt.datetime] = utcnow_column()
    ended_at: Mapped[dt.datetime | None] = mapped_column()
    assigned_by: Mapped[uuid.UUID | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(Text)

    @property
    def is_current(self) -> bool:
        return self.ended_at is None


class TenantResourceQuota(TenantOwned, Base):
    """The effective limit for one usage type over one period."""

    __tablename__ = "tenant_resource_quotas"
    __table_args__ = (UniqueConstraint("tenant_id", "usage_type", "period_start"),)

    quota_id: Mapped[uuid.UUID] = pk_uuid()
    usage_type: Mapped[str] = mapped_column(Text)
    limit_value: Mapped[int] = mapped_column(BigInteger)
    period_start: Mapped[dt.datetime] = mapped_column()
    period_end: Mapped[dt.datetime | None] = mapped_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()


class QuotaOverride(TenantOwned, Base):
    """A platform-granted exception. `reason` is not nullable, by design.

    The console requires one (dc.html L1420: "A reason is required and is written
    to the audit history"), and making the column `NOT NULL` means an override
    written by any path — including a repair script — carries its justification.
    """

    __tablename__ = "quota_overrides"

    override_id: Mapped[uuid.UUID] = pk_uuid()
    usage_type: Mapped[str] = mapped_column(Text)
    limit_value: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    granted_by: Mapped[uuid.UUID] = mapped_column()
    granted_at: Mapped[dt.datetime] = utcnow_column()
    expires_at: Mapped[dt.datetime | None] = mapped_column()
    revoked_at: Mapped[dt.datetime | None] = mapped_column()

    def is_in_force(self, now: dt.datetime) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)
