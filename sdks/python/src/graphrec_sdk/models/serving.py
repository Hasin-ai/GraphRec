from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel

__all__ = [
    "AutoscalingStatus",
    "DeploymentStatus",
    "MetricsSummary",
    "QualitySummary",
    "Replica",
    "ReplicaStatus",
]


class DeploymentStatus(GraphRecModel):
    #: ``available`` when a model is active, otherwise ``stopped``.
    status: str
    active_model_version_id: Optional[UUID] = None
    desired_model_version_id: Optional[UUID] = None
    desired_replicas: int
    current_replicas: int
    ready_replicas: int
    last_transition_at: datetime
    failure_reason: Optional[str] = None


class Replica(GraphRecModel):
    id: str
    model_version_id: Optional[UUID] = None
    status: str
    ready: bool
    started_at: datetime


class ReplicaStatus(GraphRecModel):
    desired_replicas: int
    current_replicas: int
    ready_replicas: int
    replicas: List[Replica] = Field(default_factory=list)


class AutoscalingStatus(GraphRecModel):
    min_replicas: int
    max_replicas: int
    cpu_target_percent: int
    inflight_target: Optional[int] = None
    desired_replicas: int
    ready_replicas: int
    capacity_blocked: bool
    metrics_available: bool
    recent_actions: List[Dict[str, Any]] = Field(default_factory=list)


class QualitySummary(GraphRecModel):
    hit_at_10: float
    ndcg_at_10: float
    retrieval_recall_at_k: float
    catalog_coverage: float
    intra_list_diversity: float
    training_loss: float
    validation_loss: float
    recorded_at: datetime


class MetricsSummary(GraphRecModel):
    window_start: datetime
    window_end: datetime
    request_rate: float
    error_rate: float
    fallback_rate: float
    p95_latency_ms: int
    active_model_version_id: Optional[UUID] = None
    desired_replicas: int
    ready_replicas: int
    quality: Optional[QualitySummary] = None
