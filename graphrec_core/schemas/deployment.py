from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DeploymentStatus(BaseModel):
    status: str
    active_model_version_id: UUID | None = None
    desired_model_version_id: UUID | None = None
    desired_replicas: int
    current_replicas: int
    ready_replicas: int
    last_transition_at: datetime
    failure_reason: str | None = None


class ReplicaItem(BaseModel):
    id: str
    model_version_id: UUID | None = None
    status: str
    ready: bool
    started_at: datetime


class ReplicaStatusResponse(BaseModel):
    desired_replicas: int
    current_replicas: int
    ready_replicas: int
    replicas: list[ReplicaItem]


class ScalingAction(BaseModel):
    occurred_at: datetime
    from_replicas: int
    to_replicas: int
    reason: str


class AutoscalingStatus(BaseModel):
    min_replicas: int
    max_replicas: int
    cpu_target_percent: int
    inflight_target: int | None = None
    desired_replicas: int
    ready_replicas: int
    capacity_blocked: bool
    metrics_available: bool
    recent_actions: list[dict[str, Any]] = []


class QualitySummary(BaseModel):
    hit_at_10: float
    ndcg_at_10: float
    retrieval_recall_at_k: float
    catalog_coverage: float
    intra_list_diversity: float
    training_loss: float
    validation_loss: float
    recorded_at: datetime


class MetricsSummary(BaseModel):
    window_start: datetime
    window_end: datetime
    request_rate: float
    error_rate: float
    fallback_rate: float
    p95_latency_ms: int
    active_model_version_id: UUID | None = None
    desired_replicas: int
    ready_replicas: int
    quality: QualitySummary | None = None
