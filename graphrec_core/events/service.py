from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.database.models import CustomerEvent, EventBatch, Product, UsageEvent
from graphrec_core.customers import ensure_customers
from graphrec_core.ingestion.idempotency import payload_hash
from graphrec_core.usage.limits import lock_dimension, require_capacity
from graphrec_core.errors import ApiError
from graphrec_core.schemas.events import EventBatchResponse, EventBatchSubmit, EventRecord, EventSubmit


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
                "received_at": existing.created_at.isoformat(),
            }

        self._validate_product(tenant_id, payload.external_product_id)
        require_capacity(self.db, tenant_id, "accepted_events")
        ensure_customers(self.db, tenant_id, {payload.user_id} if payload.user_id else set())
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
        digest = payload_hash(payload)
        if payload.request_id:
            previous = self.db.scalar(select(EventBatch).where(
                EventBatch.tenant_id == tenant_id, EventBatch.request_id == payload.request_id,
            ))
            if previous is not None:
                if previous.payload_hash != digest:
                    raise ApiError(409, "idempotency_conflict", "Request ID was already used with different content.")
                return EventBatchResponse.model_validate(previous)
        identifiers = {item.event_id for item in payload.events}
        existing_ids = set(self.db.scalars(select(CustomerEvent.event_id).where(
            CustomerEvent.tenant_id == tenant_id, CustomerEvent.event_id.in_(identifiers))))
        product_ids = {item.external_product_id for item in payload.events if item.external_product_id}
        known_products = set(self.db.scalars(select(Product.external_id).where(
            Product.tenant_id == tenant_id, Product.external_id.in_(product_ids)))) if product_ids else set()
        valid_new_ids = {item.event_id for item in payload.events
                         if item.event_id not in existing_ids
                         and (item.external_product_id is None or item.external_product_id in known_products)}
        require_capacity(self.db, tenant_id, "accepted_events", len(valid_new_ids))
        now = datetime.now(timezone.utc)
        accepted = 0
        duplicates = 0
        rejected = 0
        outcomes: list[dict[str, str]] = []
        seen_ids = set(existing_ids)
        accepted_customers: set[str] = set()
        new_events: list[CustomerEvent] = []

        for item in payload.events:
            if item.event_id in seen_ids:
                duplicates += 1
                outcomes.append({"event_id": item.event_id, "status": "duplicate"})
            elif item.external_product_id is not None and item.external_product_id not in known_products:
                rejected += 1
                outcomes.append({"event_id": item.event_id, "status": "rejected", "reason": "unknown_product"})
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
                new_events.append(evt)
                seen_ids.add(item.event_id)
                if item.user_id:
                    accepted_customers.add(item.user_id)
                accepted += 1
                outcomes.append({"event_id": item.event_id, "status": "accepted"})

        ensure_customers(self.db, tenant_id, accepted_customers)
        self.db.add_all(new_events)
        batch = EventBatch(
            id=uuid4(),
            tenant_id=tenant_id,
            status="completed",
            request_id=payload.request_id,
            payload_hash=digest,
            outcomes=outcomes,
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

    def list_events(
        self,
        tenant_id: UUID,
        *,
        limit: int = 50,
        user_id: str | None = None,
        event_type: str | None = None,
        external_product_id: str | None = None,
    ) -> list[EventRecord]:
        """Most recently received events first (single and batched alike)."""
        query = select(CustomerEvent).where(CustomerEvent.tenant_id == tenant_id)
        if user_id:
            query = query.where(CustomerEvent.user_id == user_id.strip())
        if event_type:
            query = query.where(CustomerEvent.event_type == event_type)
        if external_product_id:
            query = query.where(CustomerEvent.external_product_id == external_product_id.strip())
        rows = self.db.execute(
            query.order_by(CustomerEvent.created_at.desc(), CustomerEvent.id.desc()).limit(limit)
        ).scalars().all()
        return [
            EventRecord(
                event_id=row.event_id,
                event_type=row.event_type,
                user_id=row.user_id,
                external_product_id=row.external_product_id,
                context=row.context_json or {},
                occurred_at=row.occurred_at,
                created_at=row.created_at,
            )
            for row in rows
        ]

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

