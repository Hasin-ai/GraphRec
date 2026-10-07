from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.session import get_db
from graphrec_core.events.service import EventService
from graphrec_core.schemas.events import EventBatchResponse, EventBatchSubmit, EventRecord, EventSubmit, EventType

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


@router.get("/v1/events", response_model=list[EventRecord])
def list_events(
    limit: int = Query(default=50, ge=1, le=500),
    user_id: str | None = Query(default=None, max_length=256),
    event_type: EventType | None = None,
    external_product_id: str | None = Query(default=None, max_length=100),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> list[EventRecord]:
    """Recently received events, newest first, including single submissions."""
    principal.require_scope("events:read")
    service = EventService(db)
    return service.list_events(
        principal.tenant_id,
        limit=limit,
        user_id=user_id,
        event_type=event_type,
        external_product_id=external_product_id,
    )


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
