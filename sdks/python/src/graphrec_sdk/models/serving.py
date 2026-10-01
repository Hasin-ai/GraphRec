from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel

__all__ = [
    "DeploymentStatus",
    "MetricsSummary",
    "QualitySummary",
]


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
