"""Serving transition and measured traffic schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DeploymentStatus(BaseModel):
    id: UUID | None = None
    desired_model_version_id: UUID | None = None
    status: str
    active_model_version_id: UUID | None = None
    desired_capacity: int = 1
    ready_capacity: int = 0
    last_transition_at: datetime | None = None
    failure_reason: str | None = None


class QualitySummary(BaseModel):
    """Offline measures recorded for the active version at training time."""

    model_version_id: UUID
    version_tag: str
    recorded_at: datetime
    #: The version's metrics exactly as the training run recorded them; empty
    #: when the run recorded none.
    metrics: dict[str, Any] = {}


class MetricsSummary(BaseModel):
    """Serving measurements over a window of the tenant's own requests."""

    window_start: datetime
    window_end: datetime
    #: Requests recorded in the window; every rate below derives from it.
    request_count: int
    #: Requests per minute over the window.
    request_rate: float
    #: Null when no request was recorded: a rate over zero requests is undefined.
    error_rate: float | None = None
    fallback_rate: float | None = None
    #: Null when no request was served successfully in the window.
    p95_latency_ms: int | None = None
    active_model_version_id: UUID | None = None
    quality: QualitySummary | None = None


class CapacityEventResource(BaseModel):
    id: UUID
    model_version_id: UUID | None = None
    from_capacity: int
    to_capacity: int
    reason: str
    measured_rpm: int
    peak_rpm: int
    max_capacity: int
    occurred_at: datetime


class ScalingStatus(BaseModel):
    """XR-F-08: capacity policy, current capacity, live demand and recent scaling events."""

    managed: bool
    desired_capacity: int
    ready_capacity: int
    min_capacity: int = 1
    max_capacity: int
    serving_slots: int | None
    target_rpm_per_replica: int
    scale_down_stabilization_seconds: int
    measured_rpm: int
    peak_rpm: int
    last_scaled_at: datetime | None = None
    events: list[CapacityEventResource]
    limitation: str
