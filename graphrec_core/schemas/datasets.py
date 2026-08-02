from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DatasetSnapshotCreate(BaseModel):
    cutoff_at: datetime | None = None
    description: str | None = None


class DatasetSnapshotResource(BaseModel):
    id: UUID
    tenant_id: UUID
    training_job_id: UUID | None = None
    cutoff_at: datetime
    event_count: int
    product_count: int
    user_count: int
    artifact_uri: str
    checksum: str
    created_at: datetime

    class Config:
        from_attributes = True


class DatasetSnapshotListResponse(BaseModel):
    items: list[DatasetSnapshotResource]


class DatasetUploadResponse(BaseModel):
    accepted_events: int
    accepted_products: int
    dataset_snapshot: DatasetSnapshotResource
