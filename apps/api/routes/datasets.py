from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.datasets.service import DatasetService
from graphrec_core.errors import ApiError
from graphrec_core.schemas.datasets import (
    DatasetSnapshotCreate,
    DatasetSnapshotListResponse,
    DatasetSnapshotResource,
    DatasetUploadResponse,
)
from graphrec_core.settings import get_settings

router = APIRouter(tags=["datasets"])


@router.post("/v1/datasets/upload", response_model=DatasetUploadResponse)
async def upload_dataset_file(
    file: UploadFile = File(...),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> DatasetUploadResponse:
    principal.require_scope("catalog:write")
    principal.require_scope("events:write")
    limit = get_settings().max_upload_body_bytes
    content_bytes = await file.read(limit + 1)
    if len(content_bytes) > limit:
        raise ApiError(413, "payload_too_large", "The uploaded file exceeds the configured limit")
    raw_content = content_bytes.decode("utf-8", errors="ignore")
    service = DatasetService(db)
    return service.upload_dataset_content(principal.tenant_id, raw_content)


@router.post("/v1/datasets/snapshots", response_model=DatasetSnapshotResource)
def create_dataset_snapshot(
    payload: DatasetSnapshotCreate,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> DatasetSnapshotResource:
    principal.require_scope("training:write")
    service = DatasetService(db)
    return service.create_snapshot(principal.tenant_id, payload)


@router.get("/v1/datasets/snapshots", response_model=DatasetSnapshotListResponse)
def list_dataset_snapshots(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> DatasetSnapshotListResponse:
    principal.require_scope("training:read")
    service = DatasetService(db)
    items = service.list_snapshots(principal.tenant_id)
    return DatasetSnapshotListResponse(items=items)


@router.get("/v1/datasets/snapshots/{snapshot_id}", response_model=DatasetSnapshotResource)
def get_dataset_snapshot(
    snapshot_id: UUID,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> DatasetSnapshotResource:
    principal.require_scope("training:read")
    service = DatasetService(db)
    return service.get_snapshot(principal.tenant_id, snapshot_id)
