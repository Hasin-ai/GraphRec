"""Serving status schemas.

Every field here is either read from tenant state in PostgreSQL or measured
from the ``serving_requests`` ledger. Fields the platform does not observe —
replica counts, autoscaling bounds, capacity — are deliberately absent rather
than reported with nominal values.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DeploymentStatus(BaseModel):
    #: "available" when a model version is active, otherwise "stopped".
    status: str
    active_model_version_id: UUID | None = None
    #: When the active version was activated; null when nothing is active.
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
