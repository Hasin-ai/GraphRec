from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel

__all__ = [
    "CapacityEvent",
    "DeploymentStatus",
    "MetricsSummary",
    "QualitySummary",
    "RateLimiterStatus",
    "ScalingStatus",
]


class RateLimiterStatus(GraphRecModel):
    """Shared admission-control backend (Redis) as seen by the answering API process."""

    backend: str
    #: ``ok``, ``degraded`` (backend unreachable; requests fail open) or ``disabled``.
    status: str
    fail_open_total: int = 0
    last_error_at: Optional[str] = None


class DeploymentStatus(GraphRecModel):
    id: Optional[UUID] = None
    desired_model_version_id: Optional[UUID] = None
    status: str
    active_model_version_id: Optional[UUID] = None
    desired_capacity: int = 1
    ready_capacity: int = 0
    #: When the active version was activated; ``None`` when nothing is active.
    last_transition_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    rate_limiter: Optional[RateLimiterStatus] = None


class QualitySummary(GraphRecModel):
    """Offline measures recorded for the active version at training time."""

    model_version_id: UUID
    version_tag: str
    recorded_at: datetime
    #: The metrics the training run recorded, verbatim; empty when it recorded none.
    metrics: Dict[str, Any] = Field(default_factory=dict)


class MetricsSummary(GraphRecModel):
    """Serving measurements over a window of the tenant's own requests."""

    window_start: datetime
    window_end: datetime
    request_count: int
    #: Requests per minute over the window.
    request_rate: float
    #: ``None`` when no request was recorded: a rate over zero requests is undefined.
    error_rate: Optional[float] = None
    fallback_rate: Optional[float] = None
    #: ``None`` when no request was served successfully in the window.
    p95_latency_ms: Optional[int] = None
    active_model_version_id: Optional[UUID] = None
    quality: Optional[QualitySummary] = None


class CapacityEvent(GraphRecModel):
    """One recorded change of serving capacity."""

    id: UUID
    model_version_id: Optional[UUID] = None
    from_capacity: int
    to_capacity: int
    reason: str
    measured_rpm: int
    peak_rpm: int
    max_capacity: int
    occurred_at: datetime


class ScalingStatus(GraphRecModel):
    """Capacity policy, current capacity, live demand and recent scaling events."""

    managed: bool
    desired_capacity: int
    ready_capacity: int
    min_capacity: int = 1
    max_capacity: int
    #: ``None`` when the plan sets no concurrency limit.
    serving_slots: Optional[int] = None
    target_rpm_per_replica: int
    scale_down_stabilization_seconds: int
    measured_rpm: int
    peak_rpm: int
    last_scaled_at: Optional[datetime] = None
    events: List[CapacityEvent] = Field(default_factory=list)
    limitation: str
