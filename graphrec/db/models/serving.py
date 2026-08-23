"""The serving path's eight tables.

Mirrors migration 0012. Two groups: what is meant to run and what is actually
running (`ModelDeployment`, `DeploymentRevision`, `ServingReplica`,
`ModelActivationHistory`), and what the data plane answered
(`RecommendationRequest`, `RecommendationResult`, `RecommendationImpression`,
`RecommendationFeedback`).

**`desired_version_id` and `active_version_id` are two columns and the
distinction is the whole of ER-F-06.** A failed activation advances the first
and leaves the second alone; `is_serving_previous` is that fact named, so a
route can answer "did the rollback protect you?" without joining history.

**`ready_replicas` is reported by the reconciler, never inferred here.** A model
property that counted `ServingReplica` rows would be counting the last
observation, which is the same number one layer further from the truth.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from graphrec.common.enums import DeploymentState
from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column
from graphrec.serving.states import (
    HEALTHY_DEPLOYMENT_STATES,
    LIVE_REPLICA_STATUSES,
    TRANSITIONAL_DEPLOYMENT_STATES,
    ReplicaStatus,
    RequestStatus,
    RevisionKind,
    RevisionStatus,
    Strategy,
)


class ModelDeployment(Base, TenantOwned):
    """One row per tenant: what should be serving, and what is."""

    __tablename__ = "model_deployments"

    deployment_id: Mapped[uuid.UUID] = pk_uuid()
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.model_id", ondelete="CASCADE"))
    desired_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="RESTRICT")
    )
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="RESTRICT")
    )

    state: Mapped[str] = mapped_column(Text, default=DeploymentState.STOPPED.value)
    desired_replicas: Mapped[int] = mapped_column(Integer, default=0)
    ready_replicas: Mapped[int] = mapped_column(Integer, default=0)
    min_replicas: Mapped[int] = mapped_column(Integer, default=1)
    max_replicas: Mapped[int] = mapped_column(Integer, default=1)
    target_rps_per_replica: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), default=50)

    last_transition_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    epoch: Mapped[int] = mapped_column(BigInteger, default=0)

    created_at: Mapped[dt.datetime] = utcnow_column()
    updated_at: Mapped[dt.datetime] = utcnow_column()

    @property
    def deployment_state(self) -> DeploymentState:
        return DeploymentState(self.state)

    def is_healthy(self) -> bool:
        """`available` and nothing else. `degraded` serves traffic too, which is
        why it is not folded in here: the console colours the two differently
        (dc.html L1827) because one of them is a page someone should read."""
        return self.deployment_state in HEALTHY_DEPLOYMENT_STATES

    def is_settling(self) -> bool:
        """Whether the reconciler still has work to do on this row."""
        return self.deployment_state in TRANSITIONAL_DEPLOYMENT_STATES

    def is_serving_previous(self) -> bool:
        """ER-F-06 made readable: a version was asked for and a different one is
        answering, which is what a failed activation leaves behind."""
        return (
            self.active_version_id is not None
            and self.desired_version_id is not None
            and self.active_version_id != self.desired_version_id
        )

    def meets_floor(self) -> bool:
        """NR-NF-08: at least one ready replica whenever anything is desired."""
        return self.desired_replicas == 0 or self.ready_replicas >= 1

    def __repr__(self) -> str:
        return (
            f"<ModelDeployment {self.deployment_id} {self.state} "
            f"{self.ready_replicas}/{self.desired_replicas}>"
        )


class DeploymentRevision(Base, TenantOwned):
    """One attempt to change what serves. Failures are rows, not absences."""

    __tablename__ = "deployment_revisions"

    revision_id: Mapped[uuid.UUID] = pk_uuid()
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_deployments.deployment_id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    from_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="RESTRICT")
    )
    to_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(Text, default=RevisionStatus.PENDING.value)
    requested_by: Mapped[uuid.UUID | None] = mapped_column()
    requested_by_type: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime] = utcnow_column()
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def revision_status(self) -> RevisionStatus:
        return RevisionStatus(self.status)

    @property
    def revision_kind(self) -> RevisionKind:
        return RevisionKind(self.kind)

    def is_settled(self) -> bool:
        return self.revision_status is not RevisionStatus.PENDING

    def __repr__(self) -> str:
        return f"<DeploymentRevision r{self.revision} {self.kind} {self.status}>"


class ServingReplica(Base, TenantOwned):
    """One serving process as the driver last described it.

    A mirror, not a record: the reconciler overwrites and deletes rows here to
    match what it observed. Nothing downstream may treat it as history.
    """

    __tablename__ = "serving_replicas"

    replica_id: Mapped[uuid.UUID] = pk_uuid()
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_deployments.deployment_id", ondelete="CASCADE")
    )
    replica_ref: Mapped[str] = mapped_column(Text)
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(Text)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[dt.datetime] = utcnow_column()
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[dt.datetime] = utcnow_column()

    @property
    def replica_status(self) -> ReplicaStatus:
        return ReplicaStatus(self.status)

    def is_live(self) -> bool:
        """Whether the process exists, which is a different question from
        whether it can answer. `ready` is the second one."""
        return self.replica_status in LIVE_REPLICA_STATUSES

    def __repr__(self) -> str:
        return f"<ServingReplica {self.replica_ref} {self.status} ready={self.ready}>"


class ModelActivationHistory(Base, TenantOwned):
    """Who changed what was serving. Immutable — ER-F-11."""

    __tablename__ = "model_activation_history"

    activation_id: Mapped[uuid.UUID] = pk_uuid()
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.model_id", ondelete="CASCADE"))
    from_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="RESTRICT")
    )
    to_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="RESTRICT")
    )
    # No `ForeignKey`. See migration 0012: the actor may live in another table
    # or in none, and a history editable by deleting a user is not one.
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    actor_type: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<ModelActivationHistory {self.activation_id} -> {self.to_version_id}>"


class RecommendationRequest(Base, TenantOwned):
    """One answered request. ER-F-05's two fields live here."""

    __tablename__ = "recommendation_requests"

    request_id: Mapped[uuid.UUID] = pk_uuid()
    external_request_id: Mapped[str] = mapped_column(Text)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.customer_id", ondelete="SET NULL")
    )
    session_hash: Mapped[str | None] = mapped_column(Text)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.model_version_id", ondelete="SET NULL")
    )
    strategy: Mapped[str] = mapped_column(Text)
    fallback_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_count: Mapped[int] = mapped_column(Integer)
    returned_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default=RequestStatus.SERVED.value)
    # Present exactly when `status <> 'served'`, enforced by a CHECK. The reason
    # is approved copy, never a caller's string — dc.html L1842 forbids this
    # panel from carrying a payload, and a free-text column filled from a
    # request body is how that forbidding gets undone.
    error_class: Mapped[str | None] = mapped_column(Text)
    error_reason: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[dt.datetime] = utcnow_column()

    @property
    def request_strategy(self) -> Strategy:
        return Strategy(self.strategy)

    def __repr__(self) -> str:
        return f"<RecommendationRequest {self.request_id} {self.strategy} {self.status}>"


class RecommendationResult(Base, TenantOwned):
    """One returned product at one rank. Composite primary key."""

    __tablename__ = "recommendation_results"

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendation_requests.request_id", ondelete="CASCADE"), primary_key=True
    )
    rank_position: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.product_id", ondelete="CASCADE")
    )
    #: `None` on a fallback lane, where nothing scored anything. Zero would be
    #: a score, and a chart averaging it would be averaging a lie.
    model_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 6))
    final_score: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 6))
    candidate_source: Mapped[str] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<RecommendationResult #{self.rank_position} {self.product_id}>"


class RecommendationImpression(Base, TenantOwned):
    """What the tenant says they showed, at what position."""

    __tablename__ = "recommendation_impressions"

    impression_id: Mapped[uuid.UUID] = pk_uuid()
    external_event_id: Mapped[str] = mapped_column(Text)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendation_requests.request_id", ondelete="CASCADE")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.product_id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<RecommendationImpression {self.external_event_id} #{self.position}>"


class RecommendationFeedback(Base, TenantOwned):
    """Clicks and conversions. Informational only — ASM-05 says no model reads
    this back, and nothing in this phase does."""

    __tablename__ = "recommendation_feedback"

    feedback_id: Mapped[uuid.UUID] = pk_uuid()
    external_feedback_id: Mapped[str] = mapped_column(Text)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendation_requests.request_id", ondelete="CASCADE")
    )
    impression_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommendation_impressions.impression_id", ondelete="SET NULL")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.product_id", ondelete="CASCADE")
    )
    feedback_type: Mapped[str] = mapped_column(Text)
    value: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    occurred_at: Mapped[dt.datetime] = utcnow_column()

    def __repr__(self) -> str:
        return f"<RecommendationFeedback {self.feedback_type} {self.product_id}>"


__all__ = [
    "DeploymentRevision",
    "ModelActivationHistory",
    "ModelDeployment",
    "RecommendationFeedback",
    "RecommendationImpression",
    "RecommendationRequest",
    "RecommendationResult",
    "ServingReplica",
]
