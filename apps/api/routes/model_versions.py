from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
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
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    principal.require_scope("models:write")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    return service.register_model_version(principal.tenant_id, payload)


@router.get("/v1/model-versions", response_model=ModelVersionListResponse)
def list_model_versions(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionListResponse:
    principal.require_scope("models:read")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    items = service.list_model_versions(principal.tenant_id)
    return ModelVersionListResponse(items=items)


@router.get("/v1/model-versions/{version_id}", response_model=ModelVersionResource)
def get_model_version(
    version_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    principal.require_scope("models:read")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    return service.get_model_version(principal.tenant_id, version_id)


@router.post("/v1/model-versions/{version_id}:activate", response_model=ModelVersionResource)
def activate_model_version(
    version_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    principal.require_scope("models:deploy")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    return service.activate_model_version(principal.tenant_id, version_id)


@router.post("/v1/models/{model_id}:rollback", response_model=ModelVersionResource)
def rollback_model(
    model_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    principal.require_scope("models:deploy")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    return service.rollback_model(principal.tenant_id, model_id)


@router.post("/v1/model-versions/{version_id}:archive", response_model=ModelVersionResource)
def archive_model_version(
    version_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    principal.require_scope("models:write")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    return service.archive_model_version(principal.tenant_id, version_id)


@router.post("/v1/training-jobs", response_model=TrainingJobResource)
def create_training_job(
    payload: TrainingJobCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TrainingJobResource:
    principal.require_scope("training:write")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    return service.create_training_job(principal.tenant_id, payload)


@router.get("/v1/training-jobs", response_model=TrainingJobListResponse)
def list_training_jobs(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TrainingJobListResponse:
    principal.require_scope("training:read")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    items = service.list_training_jobs(principal.tenant_id)
    return TrainingJobListResponse(items=items)


@router.get("/v1/training-jobs/{job_id}", response_model=TrainingJobResource)
def get_training_job(job_id: UUID, request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal), db: Session = Depends(get_db)) -> TrainingJobResource:
    principal.require_scope("training:read")
    return ModelRegistryService(db, principal, request.state.correlation_id).get_training_job(principal.tenant_id, job_id)


@router.post("/v1/training-jobs/{job_id}:cancel", response_model=TrainingJobResource)
def cancel_training_job(job_id: UUID, request: Request,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal), db: Session = Depends(get_db)):
    principal.require_scope("training:write")
    return ModelRegistryService(db, principal, request.state.correlation_id).cancel_training(principal.tenant_id, job_id)
