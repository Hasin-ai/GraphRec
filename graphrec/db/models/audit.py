"""Audit's two tables. Mirrors migration 0013.

Neither class carries `TenantOwned`, and that is not an omission. The mixin
declares a `NOT NULL` tenant column and asserts a single `FOR ALL` policy with
matching `USING` and `WITH CHECK` — which is exactly the shape these two tables
do *not* have. Their `tenant_id` is nullable, because a platform action concerns
a tenant without belonging to one and a refused sign-in may not resolve a tenant
at all, and their policies are split so that the application role can write a
row it will never be able to read.

Mixing `TenantOwned` in to "look consistent" would make the isolation suite
assert a policy shape the migration deliberately does not use, and the test
would have to be loosened to accommodate it — trading a real structural
guarantee on twenty tables for tidiness on two.

What the migration cannot express and this module can: there is no update path.
No setter, no `updated_at`, and no relationship configured to cascade a change
into either table. Both roles hold `SELECT, INSERT` and nothing more, so an
`UPDATE` composed here fails at the database rather than in review.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from graphrec.db.models.base import Base, pk_uuid


class AuditLog(Base):
    """One decision, as it was taken.

    `details` is the only free-form column. It is never returned by the
    tenant-facing read (`GET /v1/audit-logs` projects five columns, L1288) and
    `graphrec.domain.audit.record` refuses to write a key that names a secret,
    so the blast radius of a careless caller is a platform operator seeing
    something they should not — not a tenant seeing it.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "length(resource_type) BETWEEN 1 AND 64",
            name="audit_logs_resource_type_length",
        ),
    )

    audit_log_id: Mapped[uuid.UUID] = pk_uuid()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(Text, default=None)
    action: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str] = mapped_column(Text)
    resource_ref: Mapped[str | None] = mapped_column(Text, default=None)
    outcome: Mapped[str] = mapped_column(Text)
    correlation_ref: Mapped[str | None] = mapped_column(Text, default=None)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.outcome} {self.occurred_at:%Y-%m-%dT%H:%M:%SZ}>"


class SecurityEvent(Base):
    """What went wrong, how badly, and where.

    `summary` is written by the system and never interpolated from a caller's
    input: the Failures tab renders it as prose, and prose a tenant supplied
    would be a route from one tenant's data onto a platform operator's screen.
    """

    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint("length(summary) BETWEEN 1 AND 500", name="security_events_summary_length"),
    )

    security_event_id: Mapped[uuid.UUID] = pk_uuid()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="SET NULL"), nullable=True
    )
    severity: Mapped[str] = mapped_column(Text)
    area: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    reference: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<SecurityEvent {self.severity} {self.area} {self.reference}>"
