"""Training's four tables.

Mirrors migration 0010. The predicates on `TrainingJob` are the console's own —
`can_cancel` (dc.html L1706), the rail note (L1707) — computed here so the
server and the client cannot reach different conclusions about the same row.
That matters more here than elsewhere: `/training/:jobId` polls every two
seconds, and a client deriving "still active" from its own clock will disagree
with the server about a job that finished between polls.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from graphrec.common.enums import JobState
from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column
from graphrec.training import states


class Model(Base, TenantOwned):
    """The named family a version is a version of."""

    __tablename__ = "models"

    model_id: Mapped[uuid.UUID] = pk_uuid()
    name: Mapped[str] = mapped_column(Text)
    model_type: Mapped[str] = mapped_column(Text)
    default_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<Model {self.model_id} {self.model_type}>"


class TrainingJob(Base, TenantOwned):
    """One requested run."""

    __tablename__ = "training_jobs"

    training_job_id: Mapped[uuid.UUID] = pk_uuid()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"))
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.model_id", ondelete="RESTRICT"))

    state: Mapped[str] = mapped_column(Text, default=JobState.QUEUED.value)
    stage_index: Mapped[int] = mapped_column(Integer, default=0)
    progress_text: Mapped[str] = mapped_column(Text, default="waiting to start")

    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenant_users.tenant_user_id", ondelete="SET NULL")
    )
    request_ref: Mapped[str] = mapped_column(Text)
    interaction_window_days: Mapped[int] = mapped_column(Integer)
    max_epochs: Mapped[int] = mapped_column(Integer)

    cancel_reason: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    error_reference: Mapped[str | None] = mapped_column(Text)

    requested_at: Mapped[dt.datetime] = utcnow_column()
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()

    @property
    def job_state(self) -> JobState:
        return JobState(self.state)

    def is_terminal(self) -> bool:
        return states.is_terminal(self.job_state)

    def is_active(self) -> bool:
        """L1706: "Only a job in an active state can be cancelled." """
        return states.is_active(self.job_state)

    def rail_position(self) -> int:
        """Where the rail's marker sits.

        A live or successful run is at the position its state names; a failed or
        cancelled one is at the position it stopped, which only the stored index
        knows. L1690, exactly.
        """
        if states.is_on_rail(self.job_state):
            return states.stage_index(self.job_state)
        return self.stage_index

    def stopped_at(self) -> str:
        """The stage name a terminal note quotes, as in "Stopped at
        building_graph." (L1707)."""
        return states.STAGE_NAMES[self.stage_index]

    def __repr__(self) -> str:
        """Identifiers and state only. A progress string is tenant-facing copy
        and a failure reason can name their data (NR-NF-06)."""
        return f"<TrainingJob {self.training_job_id} {self.state}>"


class DatasetSnapshot(Base, TenantOwned):
    """What one run read, frozen at `cutoff_at`.

    No `updated_at`. There is no `UPDATE` grant on this table, so a column
    recording when it was last changed would be a column that can only ever hold
    the creation time under a misleading name.
    """

    __tablename__ = "dataset_snapshots"

    snapshot_id: Mapped[uuid.UUID] = pk_uuid()
    training_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("training_jobs.training_job_id", ondelete="CASCADE")
    )
    cutoff_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    window_days: Mapped[int] = mapped_column(Integer)
    uri: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(Text)
    sequence_count: Mapped[int] = mapped_column(Integer)
    product_count: Mapped[int] = mapped_column(Integer)
    event_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<DatasetSnapshot {self.snapshot_id} {self.window_days}d>"


class TrainingMetric(Base, TenantOwned):
    """One measurement, at one epoch, of one thing."""

    __tablename__ = "training_metrics"

    metric_id: Mapped[uuid.UUID] = pk_uuid()
    training_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("training_jobs.training_job_id", ondelete="CASCADE")
    )
    epoch: Mapped[int] = mapped_column(Integer)
    metric_name: Mapped[str] = mapped_column(Text)
    value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    recorded_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<TrainingMetric {self.metric_name}@{self.epoch}={self.value}>"


__all__ = ["DatasetSnapshot", "Model", "TrainingJob", "TrainingMetric"]
