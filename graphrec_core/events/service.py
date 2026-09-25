from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.database.models import CustomerEvent, EventBatch, Product, UsageEvent
from graphrec_core.usage.limits import lock_dimension, require_capacity
from graphrec_core.errors import ApiError
from graphrec_core.schemas.events import EventBatchResponse, EventBatchSubmit, EventSubmit


class EventService:
    def __init__(self, db: Session):
        self.db = db

    def submit_event(self, tenant_id: UUID, payload: EventSubmit) -> dict[str, Any]:
        lock_dimension(self.db, tenant_id, "accepted_events")
        now = datetime.now(timezone.utc)
        existing = self.db.execute(
            select(CustomerEvent).where(
                CustomerEvent.tenant_id == tenant_id, CustomerEvent.event_id == payload.event_id
            )
        ).scalar_one_or_none()

        if existing:
            return {
                "event_id": payload.event_id,
                "accepted": True,
                "duplicate": True,
                "received_at": now.isoformat(),
            }

        self._validate_product(tenant_id, payload.external_product_id)
        require_capacity(self.db, tenant_id, "accepted_events")
        event = CustomerEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            event_id=payload.event_id,
            event_type=payload.event_type,
            user_id=payload.user_id,
            external_product_id=payload.external_product_id,
            context_json=payload.context,
            occurred_at=payload.occurred_at,
            created_at=now,
        )
        self.db.add(event)

        usage = UsageEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            usage_type="accepted_events",
            quantity=Decimal("1"),
            source_id=f"event-{payload.event_id}",
            idempotency_key=f"event-usage-{payload.event_id}",
            occurred_at=now,
        )
        self.db.add(usage)
        self.db.commit()

        return {
            "event_id": payload.event_id,
            "accepted": True,
            "duplicate": False,
            "received_at": now.isoformat(),
        }

    def submit_batch(self, tenant_id: UUID, payload: EventBatchSubmit) -> EventBatchResponse:
        lock_dimension(self.db, tenant_id, "accepted_events")
        identifiers = {item.event_id for item in payload.events}
        existing_ids = set(self.db.scalars(select(CustomerEvent.event_id).where(
            CustomerEvent.tenant_id == tenant_id, CustomerEvent.event_id.in_(identifiers))))
        for item in payload.events:
            if item.event_id not in existing_ids:
                self._validate_product(tenant_id, item.external_product_id)
        require_capacity(self.db, tenant_id, "accepted_events", len(identifiers - existing_ids))
        now = datetime.now(timezone.utc)
        accepted = 0
        duplicates = 0
        rejected = 0

        for item in payload.events:
            existing = self.db.execute(
                select(CustomerEvent).where(
                    CustomerEvent.tenant_id == tenant_id, CustomerEvent.event_id == item.event_id
                )
            ).scalar_one_or_none()

            if existing:
                duplicates += 1
            else:
                evt = CustomerEvent(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    event_id=item.event_id,
                    event_type=item.event_type,
                    user_id=item.user_id,
                    external_product_id=item.external_product_id,
                    context_json=item.context,
                    occurred_at=item.occurred_at,
                    created_at=now,
                )
                self.db.add(evt)
                accepted += 1

        batch = EventBatch(
            id=uuid4(),
            tenant_id=tenant_id,
            status="completed",
            accepted_count=accepted,
            duplicate_count=duplicates,
            rejected_count=rejected,
            created_at=now,
        )
        self.db.add(batch)

        if accepted > 0:
            usage = UsageEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                usage_type="accepted_events",
                quantity=Decimal(accepted),
                source_id=f"batch-{batch.id}",
                idempotency_key=str(uuid4()),
                occurred_at=now,
            )
            self.db.add(usage)

        self.db.commit()
        return EventBatchResponse.model_validate(batch)

    def get_batch(self, tenant_id: UUID, batch_id: UUID) -> EventBatchResponse:
        batch = self.db.execute(
            select(EventBatch).where(
                EventBatch.tenant_id == tenant_id, EventBatch.id == batch_id
            )
        ).scalar_one_or_none()

        if not batch:
            raise ApiError(404, "resource_not_found", f"Event batch '{batch_id}' not found.")

        return EventBatchResponse.model_validate(batch)

    def _validate_product(self, tenant_id: UUID, external_id: str | None) -> None:
        if external_id is not None and self.db.scalar(select(Product.id).where(
            Product.tenant_id == tenant_id, Product.external_id == external_id)) is None:
            raise ApiError(422, "invalid_product_reference", "The event product does not exist in this tenant catalog.")

    def list_batches(self, tenant_id: UUID) -> list[EventBatchResponse]:
        batches = (
            self.db.execute(
                select(EventBatch)
                .where(EventBatch.tenant_id == tenant_id)
                .order_by(EventBatch.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [EventBatchResponse.model_validate(b) for b in batches]

