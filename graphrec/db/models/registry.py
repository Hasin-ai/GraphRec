"""The registry's two tables.

Mirrors migration 0011. The lifecycle predicates are the console's own — the
`actions` block on `/models/:versionId` (dc.html L1748-1770) — computed here so
the button's enabled state and the endpoint's refusal come from one function.

**What is *not* here is the archive rule.** "A retired version immediately
preceding the active one is retained as the rollback target" (L1749) is a
question about another row, and a model that answered it would have to guess at
one. `graphrec.domain.registry` asks it, and `ModelVersion.archivable_status`
answers only the part that is visible from this row.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from graphrec.common.enums import ModelVersionStatus
from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column

#: L1168: archiving is allowed from these three, and `retired` is conditional on
#: a question this row cannot answer.
ARCHIVABLE = frozenset(
    {
        ModelVersionStatus.REGISTERED,
        ModelVersionStatus.REJECTED,
        ModelVersionStatus.RETIRED,
    }
)

#: The states that mean "this version was measured and found wanting", as
#: opposed to `failed_deployment`, which means it was measured, found good, and
#: then failed to load. Keeping them distinct is ADR 0027's point.
UNSERVEABLE = frozenset({ModelVersionStatus.REJECTED, ModelVersionStatus.FAILED_DEPLOYMENT})


class ModelVersion(Base, TenantOwned):
    """One trained artifact and where it is in its life.

    Immutable after registration except for `status`, `failure_note` and
    `archived_at` — not by convention but by grant (migration 0011). A service
    that tried to correct a digest here would be refused by PostgreSQL.
    """

    __tablename__ = "model_versions"

    model_version_id: Mapped[uuid.UUID] = pk_uuid()
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.model_id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default=ModelVersionStatus.REGISTERED.value)

    training_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("training_jobs.training_job_id", ondelete="RESTRICT")
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_snapshots.snapshot_id", ondelete="RESTRICT")
    )

    artifact_uri: Mapped[str] = mapped_column(Text)
    artifact_digest: Mapped[str] = mapped_column(Text)
    feature_contract: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding_dim: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    failure_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[dt.datetime] = utcnow_column()
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def version_status(self) -> ModelVersionStatus:
        return ModelVersionStatus(self.status)

    def is_active(self) -> bool:
        return self.version_status is ModelVersionStatus.ACTIVE

    def is_eligible(self) -> bool:
        """L1737's `eligible` card, and the only state `:activate` accepts."""
        return self.version_status is ModelVersionStatus.ELIGIBLE

    def is_archived(self) -> bool:
        """The bytes are gone. The row and its metrics are not."""
        return self.version_status is ModelVersionStatus.ARCHIVED

    def archivable_status(self) -> bool:
        """Whether the *status* permits archiving, ignoring the rollback rule."""
        return self.version_status in ARCHIVABLE

    def label(self) -> str:
        """ "Version 7", as the console writes it (L1730)."""
        return f"Version {self.version_number}"

    def __repr__(self) -> str:
        """Identifiers and status only. `metrics` is the tenant's business and
        `failure_note` is tenant-facing copy."""
        return f"<ModelVersion {self.model_version_id} v{self.version_number} {self.status}>"


class ModelEvaluationMetric(Base, TenantOwned):
    """One measurement of one version on one split.

    No `updated_at`, for the reason `TrainingMetric` has none: there is no
    `UPDATE` grant on this table, and a measure that can be revised after the
    decision it justified is not evidence.
    """

    __tablename__ = "model_evaluation_metrics"

    metric_id: Mapped[uuid.UUID] = pk_uuid()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="CASCADE")
    )
    split: Mapped[str] = mapped_column(Text)
    metric_name: Mapped[str] = mapped_column(Text)
    value: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 6))
    created_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<ModelEvaluationMetric {self.split}.{self.metric_name}={self.value}>"


__all__ = [
    "ARCHIVABLE",
    "UNSERVEABLE",
    "ModelEvaluationMetric",
    "ModelVersion",
]
