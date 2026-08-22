"""The job queue's one table.

Mirrors migration 0006. The lifecycle predicates live on the model for the same
reason they live on `ApiKey`: the console derives `cancelling` from a state and
a timestamp (dc.html L1718), and a client that derives it from its own clock
will disagree with the server about whether a lease has lapsed.

Note that `attempt` counts the retry budget *consumed*, not the number of times
the job has been picked up. Claiming does not spend one. The difference is the
whole of "a deterministic failure consumes no attempts".
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column
from graphrec.jobs.states import TERMINAL_STATUSES, QueueStatus


class Job(Base, TenantOwned):
    """One unit of deferred work, owned by exactly one tenant."""

    __tablename__ = "jobs"

    job_id: Mapped[uuid.UUID] = pk_uuid()
    job_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default=QueueStatus.QUEUED.value)
    priority: Mapped[int] = mapped_column(Integer, default=5)

    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[dt.datetime] = utcnow_column()

    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    cancel_requested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    failure_code: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def queue_status(self) -> QueueStatus:
        return QueueStatus(self.status)

    def is_terminal(self) -> bool:
        return self.queue_status in TERMINAL_STATUSES

    def is_active(self) -> bool:
        """dc.html L1706: "Only a job in an active state can be cancelled." """
        return not self.is_terminal()

    def is_cancelling(self) -> bool:
        """Cancellation requested, but the worker has not yet reached a boundary.

        The prototype shows this as its own badge (L1718 sets `cancelling`, and
        L860 later settles it to `cancelled`). It is not a stored status here:
        it is `running` plus a request, because a second column that can
        disagree with the first is a second source of truth.
        """
        return self.cancel_requested_at is not None and not self.is_terminal()

    def lease_has_lapsed(self, *, now: dt.datetime) -> bool:
        return (
            self.queue_status is QueueStatus.RUNNING
            and self.lease_expires_at is not None
            and self.lease_expires_at <= now
        )

    def attempts_remaining(self) -> int:
        return max(0, self.max_attempts - self.attempt)

    def __repr__(self) -> str:
        """Identifiers and status only.

        A payload is tenant data and this string reaches logs (NR-NF-06).
        """
        return f"<Job {self.job_id} {self.job_type} {self.status}>"
