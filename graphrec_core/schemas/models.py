from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ModelVersionCreate(BaseModel):
    version_tag: str = Field(..., max_length=64)
    model_type: str = Field(..., max_length=64)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None


class ModelVersionResource(BaseModel):
    id: UUID
    version_tag: str
    model_type: str
    status: str
    metrics: dict[str, Any]
    artifact_uri: str | None = None
    qdrant_collection: str | None = None
    created_at: datetime
    activated_at: datetime | None = None

    class Config:
        from_attributes = True


class ModelVersionListResponse(BaseModel):
    items: list[ModelVersionResource]


class TrainingJobCreate(BaseModel):
    model_type: str = Field(default="simplified_dgsr", max_length=64)
    dataset_snapshot_id: UUID | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)


class TrainingJobResource(BaseModel):
    id: UUID
    model_type: str
    status: str
    configuration: dict[str, Any]
    dataset_snapshot_id: UUID | None = None
    model_version_id: UUID | None = None
    qdrant_collection: str | None = None
    failure_reason: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    class Config:
        from_attributes = True


class TrainingJobListResponse(BaseModel):
    items: list[TrainingJobResource]
