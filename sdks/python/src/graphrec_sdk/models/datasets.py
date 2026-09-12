from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from ._base import GraphRecModel, ItemList

__all__ = ["DatasetSnapshot", "DatasetSnapshotList", "DatasetUploadResult"]


class DatasetSnapshot(GraphRecModel):
    """An immutable, tenant-scoped view of catalog and events used for training."""

    id: UUID
    tenant_id: UUID
    training_job_id: Optional[UUID] = None
    cutoff_at: datetime
    event_count: int
    product_count: int
    user_count: int
    artifact_uri: str
    #: SHA-256 over the included identifiers; equal checksums mean equal data.
    checksum: str
    created_at: datetime


class DatasetSnapshotList(ItemList[DatasetSnapshot]):
    pass


class DatasetUploadResult(GraphRecModel):
    accepted_events: int
    accepted_products: int
    dataset_snapshot: DatasetSnapshot
