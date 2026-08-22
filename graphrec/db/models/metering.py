"""Metering's two tables: the ledger and its rollup.

Mirrors migration 0009. The division is described there — `UsageEvent` is an
append-only grant, `MonthlyUsageAggregate` is a derived account of many grants —
and the mapping carries one thing the migration cannot: the reminder that
`UsageEvent` has **no** update path. There is no setter, no `updated_at`, and
`graphrec_app` holds no `UPDATE` grant. Reaching for one should feel like
reaching for something that is not there, because it is not.

`MonthlyUsageAggregate.quantity` is nullable and `measurement_status` is not.
That asymmetry is the phase's contract in two lines: we always know *whether* we
measured, and we sometimes do not know *what*.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid

from sqlalchemy import CheckConstraint, Date, DateTime, Numeric, PrimaryKeyConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from graphrec.common.enums import MeasurementStatus
from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column


class UsageEvent(Base, TenantOwned):
    """One grant of usage, as it happened, forever.

    Written inside the transaction that creates whatever is being metered, so
    that a rolled-back submission does not leave a tenant charged for it. The
    unique key on `(tenant_id, idempotency_key)` is what makes that write safe
    to retry.
    """

    __tablename__ = "usage_events"

    usage_event_id: Mapped[uuid.UUID] = pk_uuid()
    usage_type: Mapped[str] = mapped_column(Text)
    quantity: Mapped[decimal.Decimal] = mapped_column(Numeric(20, 4))
    source_ref: Mapped[str | None] = mapped_column(Text, default=None)
    idempotency_key: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<UsageEvent {self.usage_event_id} {self.usage_type}>"


class MonthlyUsageAggregate(Base, TenantOwned):
    """What the ledger came to, for one tenant, one period, one type."""

    __tablename__ = "monthly_usage_aggregates"
    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id", "period_start", "usage_type", name="pk_monthly_usage_aggregates"
        ),
        CheckConstraint(
            "(measurement_status = 'measured') = (quantity IS NOT NULL)",
            name="ck_mua_measured_iff_quantity",
        ),
    )

    period_start: Mapped[dt.date] = mapped_column(Date)
    usage_type: Mapped[str] = mapped_column(Text)
    quantity: Mapped[decimal.Decimal | None] = mapped_column(Numeric(20, 4), default=None)
    measurement_status: Mapped[str] = mapped_column(Text, default=MeasurementStatus.DELAYED.value)
    computed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<MonthlyUsageAggregate {self.period_start} {self.usage_type}>"


__all__ = ["MonthlyUsageAggregate", "UsageEvent"]
