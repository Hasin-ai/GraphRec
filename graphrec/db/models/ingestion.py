"""Ingestion's five tables.

Mirrors migration 0008. The division is described there: `Customer` and
`InteractionEvent` are facts, `Submission` and `SubmissionError` are the account
of how those facts arrived, and `IngestStagingItem` is scratch space that is
empty whenever nobody is mid-merge.

Every `__repr__` here is deliberately identifier-only. These objects hold a
tenant's customers, what they looked at and what they bought; a repr reaches
logs, and none of that belongs there (NR-NF-06).
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from graphrec.common.enums import SubmissionKind, SubmissionStatus
from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column

#: A submission stops changing here. The console reads it as "Processing
#: finished." (dc.html L1386) and stops polling.
TERMINAL_SUBMISSION_STATUSES = frozenset({SubmissionStatus.COMPLETED, SubmissionStatus.FAILED})


class Customer(Base, TenantOwned):
    """A person, in the tenant's own vocabulary and nobody else's."""

    __tablename__ = "customers"

    customer_id: Mapped[uuid.UUID] = pk_uuid()
    external_customer_id: Mapped[str] = mapped_column(Text)

    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<Customer {self.customer_id}>"


class Submission(Base, TenantOwned):
    """One arrival, and the running account of what became of it."""

    __tablename__ = "submissions"

    submission_id: Mapped[uuid.UUID] = pk_uuid()
    kind: Mapped[str] = mapped_column(Text)
    external_reference: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default=SubmissionStatus.RECEIVED.value)

    received_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    #: How many failures were *kept* as samples. `failed_count` stays exact.
    error_count: Mapped[int] = mapped_column(Integer, default=0)

    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.job_id", ondelete="SET NULL"))
    #: Cleared on completion. See migration 0008 — the shortest-lived copy of a
    #: tenant's raw data is the safest one.
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    failure_code: Mapped[str | None] = mapped_column(Text)

    submitted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()

    @property
    def submission_kind(self) -> SubmissionKind:
        return SubmissionKind(self.kind)

    @property
    def submission_status(self) -> SubmissionStatus:
        return SubmissionStatus(self.status)

    def is_terminal(self) -> bool:
        return self.submission_status in TERMINAL_SUBMISSION_STATUSES

    def handled_count(self) -> int:
        """Items whose fate is decided — what the progress percentage divides.

        The console computes `(accepted + failed + skipped) / received` (L1380).
        `updated_count` is not added: an updated product was also an accepted
        one, and counting it twice would put the rail past 100%.
        """
        return self.accepted_count + self.failed_count + self.skipped_count

    def __repr__(self) -> str:
        return f"<Submission {self.submission_id} {self.kind} {self.status}>"


class InteractionEvent(Base, TenantOwned):
    """One interaction. Written once and never corrected."""

    __tablename__ = "interaction_events"

    event_id: Mapped[uuid.UUID] = pk_uuid()
    external_event_id: Mapped[str] = mapped_column(Text)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.customer_id", ondelete="CASCADE")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.product_id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(Text)

    #: The tenant's clock. `received_at` is ours, and the split that trains the
    #: model uses this one.
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))

    value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 2))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("submissions.submission_id", ondelete="SET NULL")
    )

    def __repr__(self) -> str:
        # Not the customer, not the product, not the type. Who bought what is
        # the tenant's commercial data.
        return f"<InteractionEvent {self.event_id}>"


class SubmissionError(Base, TenantOwned):
    """One kept sample of a per-item failure."""

    __tablename__ = "submission_errors"

    submission_error_id: Mapped[uuid.UUID] = pk_uuid()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submissions.submission_id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    item_reference: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    #: Approved copy, resolved from `ITEM_ERROR_COPY` by `code`. Never a
    #: formatted exception and never any part of the submitted item.
    reason: Mapped[str] = mapped_column(Text)

    created_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<SubmissionError {self.submission_error_id}>"


class IngestStagingItem(Base, TenantOwned):
    """A validated item, waiting for the merge that will apply it."""

    __tablename__ = "ingest_staging_items"

    staging_item_id: Mapped[uuid.UUID] = pk_uuid()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submissions.submission_id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    item: Mapped[dict[str, Any]] = mapped_column(JSONB)

    def __repr__(self) -> str:
        return f"<IngestStagingItem {self.staging_item_id}>"
