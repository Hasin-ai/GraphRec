from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel, ItemList

__all__ = ["ModelVersion", "ModelVersionList", "TrainingJob", "TrainingJobList"]

_TERMINAL_TRAINING_STATES = frozenset({"succeeded", "failed", "cancelled"})


class ModelVersion(GraphRecModel):
    id: UUID
    version_tag: str
    #: e.g. ``simplified_dgsr``.
    model_type: str
    #: ``eligible``, ``active``, ``retired`` or ``archived``.
    status: str
    #: Offline quality, e.g. ``{"recall_at_10": 0.85, "ndcg_at_10": 0.78}``.
    metrics: Dict[str, Any] = Field(default_factory=dict)
    artifact_uri: Optional[str] = None
    qdrant_collection: Optional[str] = None
    created_at: datetime
    activated_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"


class ModelVersionList(ItemList[ModelVersion]):
    @property
    def active(self) -> Optional[ModelVersion]:
        """The serving version, if any."""

        return next((item for item in self.items if item.is_active), None)


class TrainingJob(GraphRecModel):
    id: UUID
    model_type: str
    #: ``queued``, ``preparing_data``, ``training``, ``succeeded``, ``failed`` (or ``cancelled``).
    status: str
    configuration: Dict[str, Any] = Field(default_factory=dict)
    dataset_snapshot_id: Optional[UUID] = None
    model_version_id: Optional[UUID] = None
    qdrant_collection: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_TRAINING_STATES

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"


class TrainingJobList(ItemList[TrainingJob]):
    pass
