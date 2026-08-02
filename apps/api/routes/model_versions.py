from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.models_reg.service import ModelRegistryService
from graphrec_core.schemas.models import (
    ModelVersionCreate,
    ModelVersionListResponse,
    ModelVersionResource,
    TrainingJobCreate,
    TrainingJobListResponse,
    TrainingJobResource,
)

router = APIRouter(tags=["models"])


@router.post("/v1/model-versions", response_model=ModelVersionResource)
def register_model_version(
    payload: ModelVersionCreate,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    service = ModelRegistryService(db)
    return service.register_model_version(principal.tenant_id, payload)


@router.get("/v1/model-versions", response_model=ModelVersionListResponse)
def list_model_versions(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionListResponse:
    service = ModelRegistryService(db)
    items = service.list_model_versions(principal.tenant_id)
    return ModelVersionListResponse(items=items)


@router.get("/v1/model-versions/{version_id}", response_model=ModelVersionResource)
def get_model_version(
    version_id: UUID,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    service = ModelRegistryService(db)
    return service.get_model_version(principal.tenant_id, version_id)


@router.post("/v1/model-versions/{version_id}:activate", response_model=ModelVersionResource)
def activate_model_version(
    version_id: UUID,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    service = ModelRegistryService(db)
    return service.activate_model_version(principal.tenant_id, version_id)


@router.post("/v1/models/{model_id}:rollback", response_model=ModelVersionResource)
def rollback_model(
    model_id: UUID,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    service = ModelRegistryService(db)
    return service.rollback_model(principal.tenant_id, model_id)


@router.post("/v1/model-versions/{version_id}:archive", response_model=ModelVersionResource)
def archive_model_version(
    version_id: UUID,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    service = ModelRegistryService(db)
    return service.archive_model_version(principal.tenant_id, version_id)


@router.post("/v1/training-jobs", response_model=TrainingJobResource)
def create_training_job(
    payload: TrainingJobCreate,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TrainingJobResource:
    service = ModelRegistryService(db)
    return service.create_training_job(principal.tenant_id, payload)


@router.get("/v1/training-jobs", response_model=TrainingJobListResponse)
def list_training_jobs(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TrainingJobListResponse:
    service = ModelRegistryService(db)
    items = service.list_training_jobs(principal.tenant_id)
    return TrainingJobListResponse(items=items)
