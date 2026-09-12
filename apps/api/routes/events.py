from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.events.service import EventService
from graphrec_core.schemas.events import EventBatchResponse, EventBatchSubmit, EventSubmit

router = APIRouter(tags=["events"])


@router.post("/v1/events")
def submit_event(
    payload: EventSubmit,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal.require_scope("events:write")
    service = EventService(db)
    return service.submit_event(principal.tenant_id, payload)


@router.post("/v1/events/batches", response_model=EventBatchResponse)
def submit_event_batch(
    payload: EventBatchSubmit,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> EventBatchResponse:
    principal.require_scope("events:write")
    service = EventService(db)
    return service.submit_batch(principal.tenant_id, payload)


@router.get("/v1/events/batches", response_model=list[EventBatchResponse])
def list_event_batches(
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> list[EventBatchResponse]:
    principal.require_scope("events:read")
    service = EventService(db)
    return service.list_batches(principal.tenant_id)


@router.get("/v1/events/batches/{batch_id}", response_model=EventBatchResponse)
def get_event_batch(
    batch_id: UUID,
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> EventBatchResponse:
    principal.require_scope("events:read")
    service = EventService(db)
    return service.get_batch(principal.tenant_id, batch_id)
