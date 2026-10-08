from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.database.tenancy import set_audit_reason
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


class LifecycleReason(BaseModel):
    """Optional body of lifecycle actions (UC-14, UC-18, UC-19, UC-20): the
    reason is stored with the action's audit record (ER-F-11)."""

    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


def _reason(db: Session, payload: LifecycleReason | None) -> None:
    set_audit_reason(db, payload.reason if payload else None)


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
    payload: LifecycleReason | None = Body(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    principal.require_scope("models:deploy")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    _reason(db, payload)
    return service.activate_model_version(principal.tenant_id, version_id)


@router.post("/v1/model-versions/{version_id}:rollback", response_model=ModelVersionResource)
def rollback_to_version(
    version_id: UUID,
    request: Request,
    payload: LifecycleReason | None = Body(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    """Roll back to the retained version ``version_id`` (A-36: same as the
    older ``/v1/models/{model_id}:rollback``, whose parameter is a version id)."""
    principal.require_scope("models:deploy")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    _reason(db, payload)
    return service.rollback_model(principal.tenant_id, version_id)


@router.post("/v1/models/{model_id}:rollback", response_model=ModelVersionResource, deprecated=True)
def rollback_model(
    model_id: UUID,
    request: Request,
    payload: LifecycleReason | None = Body(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    principal.require_scope("models:deploy")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    _reason(db, payload)
    return service.rollback_model(principal.tenant_id, model_id)


@router.post("/v1/model-versions/{version_id}:archive", response_model=ModelVersionResource)
def archive_model_version(
    version_id: UUID,
    request: Request,
    payload: LifecycleReason | None = Body(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> ModelVersionResource:
    principal.require_scope("models:write")
    service = ModelRegistryService(db, principal, request.state.correlation_id)
    _reason(db, payload)
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
    payload: LifecycleReason | None = Body(default=None),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal), db: Session = Depends(get_db)):
    principal.require_scope("training:write")
    _reason(db, payload)
    return ModelRegistryService(db, principal, request.state.correlation_id).cancel_training(principal.tenant_id, job_id)
