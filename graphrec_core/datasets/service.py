from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from graphrec_core.catalog.service import CatalogService
from graphrec_core.database.models import CustomerEvent, DatasetSnapshot, DatasetSnapshotContent, EventBatch, Product, UsageEvent
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.events.service import EventService
from graphrec_core.usage.limits import lock_dimension, require_capacity
from graphrec_core.schemas.datasets import (
    DatasetSnapshotCreate,
    DatasetSnapshotResource,
    DatasetUploadResponse,
)
from graphrec_core.schemas.events import EventBatchSubmit
from graphrec_core.schemas.products import ProductBulkUpsertRequest


BULK_CHUNK = 2_000


class DatasetService:
    def __init__(self, db: Session):
        self.db = db

    def upload_dataset_content(self, tenant_id: UUID, raw_content: str) -> DatasetUploadResponse:
        interactions = _parse_interaction_log(raw_content)
        if interactions is not None:
            return self.load_interaction_log(tenant_id, interactions)
        products, events = _parse_dataset(raw_content)
        if not products and not events:
            raise ApiError(
                422,
                "validation_failed",
                "The dataset contains no products or events",
            )

        accepted_products = 0
        accepted_events = 0
        try:
            if products:
                request = ProductBulkUpsertRequest(products=products)
                result = CatalogService(self.db).bulk_upsert(tenant_id, request)
                accepted_products = result.accepted_count
            if events:
                # bulk_upsert committed, which clears the transaction-local tenant context
                set_local_tenant(self.db, tenant_id)
                batch = EventService(self.db).submit_batch(
                    tenant_id, EventBatchSubmit(events=events)
                )
                accepted_events = batch.accepted_count
        except ValidationError as exc:
            raise ApiError(
                422,
                "validation_failed",
                "The dataset contains invalid records",
                details={"errors": exc.errors(include_url=False)},
            ) from exc

        snapshot = self.create_snapshot(tenant_id, DatasetSnapshotCreate())
        return DatasetUploadResponse(
            accepted_events=accepted_events,
            accepted_products=accepted_products,
            dataset_snapshot=snapshot,
        )

    def load_interaction_log(
        self, tenant_id: UUID, interactions: list[tuple[str, str, int]]
    ) -> DatasetUploadResponse:
        """Bulk-load a ``user_id,item_id,time`` interaction log.

        This is the format sequential recommenders (and the DGSR notebook) are
        trained on. Unknown items become minimal active products; every row
        becomes a ``purchase`` event with a deterministic id, so re-uploading
        the same file records duplicates rather than double counting. Rows are
        inserted in chunks with ``ON CONFLICT DO NOTHING`` (a few hundred
        thousand rows take seconds, not the minutes of the per-record path).
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        now = datetime.now(timezone.utc)
        set_local_tenant(self.db, tenant_id)

        item_ids = list(dict.fromkeys(item for _, item, _ in interactions))
        lock_dimension(self.db, tenant_id, "stored_products")
        lock_dimension(self.db, tenant_id, "accepted_events")
        existing_items = set(self.db.scalars(select(Product.external_id).where(
            Product.tenant_id == tenant_id, Product.external_id.in_(item_ids))))
        require_capacity(self.db, tenant_id, "stored_products", len(set(item_ids) - existing_items))
        product_rows = [
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "external_id": item,
                "title": f"Item {item}",
                "description": None,
                "price": Decimal("0.00"),
                "category": None,
                "is_active": True,
                "availability_status": "available",
                "metadata_json": {"source": "interaction_log"},
                "created_at": now,
                "updated_at": now,
            }
            for item in item_ids
        ]
        # ``rowcount`` is unreliable for multi-row ON CONFLICT inserts (psycopg
        # reports -1), so accepted counts come from before/after row counts.
        products_before = self._count(Product, tenant_id)
        for start in range(0, len(product_rows), BULK_CHUNK):
            chunk = product_rows[start : start + BULK_CHUNK]
            statement = pg_insert(Product).values(chunk).on_conflict_do_nothing(
                index_elements=["tenant_id", "external_id"]
            )
            self.db.execute(statement)
        accepted_products = self._count(Product, tenant_id) - products_before

        occurrences: dict[tuple[str, str, int], int] = {}
        event_rows = []
        for user, item, moment in interactions:
            key = (user, item, moment)
            ordinal = occurrences.get(key, 0)
            occurrences[key] = ordinal + 1
            suffix = f":{ordinal}" if ordinal else ""
            event_rows.append(
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "event_id": f"il:{user}:{item}:{moment}{suffix}",
                    "event_type": "purchase",
                    "user_id": user,
                    "external_product_id": item,
                    "context_json": {"source": "interaction_log"},
                    "occurred_at": datetime.fromtimestamp(moment, tz=timezone.utc),
                    "created_at": now,
                }
            )
        events_before = self._count(CustomerEvent, tenant_id)
        new_event_count = 0
        for start in range(0, len(event_rows), BULK_CHUNK):
            ids = {row["event_id"] for row in event_rows[start:start + BULK_CHUNK]}
            existing = set(self.db.scalars(select(CustomerEvent.event_id).where(
                CustomerEvent.tenant_id == tenant_id, CustomerEvent.event_id.in_(ids))))
            new_event_count += len(ids - existing)
        require_capacity(self.db, tenant_id, "accepted_events", new_event_count)
        for start in range(0, len(event_rows), BULK_CHUNK):
            chunk = event_rows[start : start + BULK_CHUNK]
            statement = pg_insert(CustomerEvent).values(chunk).on_conflict_do_nothing(
                index_elements=["tenant_id", "event_id"]
            )
            self.db.execute(statement)
        accepted_events = self._count(CustomerEvent, tenant_id) - events_before

        for usage_type, quantity, source in (
            ("stored_products", accepted_products, "interaction-log-products"),
            ("accepted_events", accepted_events, "interaction-log-events"),
        ):
            if quantity > 0:
                self.db.add(
                    UsageEvent(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        usage_type=usage_type,
                        quantity=Decimal(quantity),
                        source_id=f"{source}-{now.timestamp()}",
                        idempotency_key=str(uuid4()),
                        occurred_at=now,
                    )
                )
        self.db.add(
            EventBatch(
                id=uuid4(),
                tenant_id=tenant_id,
                status="completed",
                accepted_count=accepted_events,
                duplicate_count=len(event_rows) - accepted_events,
                rejected_count=0,
                created_at=now,
            )
        )
        self.db.commit()
        snapshot = self.create_snapshot(tenant_id, DatasetSnapshotCreate())
        return DatasetUploadResponse(
            accepted_events=accepted_events,
            accepted_products=accepted_products,
            dataset_snapshot=snapshot,
        )

    def _count(self, model: type[Product] | type[CustomerEvent], tenant_id: UUID) -> int:
        return int(
            self.db.execute(
                select(func.count(model.id)).where(model.tenant_id == tenant_id)
            ).scalar_one()
        )

    def create_snapshot(
        self, tenant_id: UUID, payload: DatasetSnapshotCreate, *, commit: bool = True
    ) -> DatasetSnapshotResource:
        now = datetime.now(timezone.utc)
        cutoff = payload.cutoff_at or now
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)

        set_local_tenant(self.db, tenant_id)
        events = list(self.db.scalars(select(CustomerEvent).where(
            CustomerEvent.tenant_id == tenant_id, CustomerEvent.occurred_at <= cutoff
        ).order_by(CustomerEvent.occurred_at, CustomerEvent.event_id)))
        products = list(self.db.scalars(select(Product).where(
            Product.tenant_id == tenant_id, Product.is_active.is_(True)
        ).order_by(Product.external_id)))
        content = {
            "tenant_id": str(tenant_id), "cutoff_at": cutoff.isoformat(),
            "products": [{"external_id": p.external_id, "title": p.title, "category": p.category,
                "price": str(p.price), "availability_status": p.availability_status, "metadata": p.metadata_json} for p in products],
            "events": [{"event_id": e.event_id, "event_type": e.event_type, "user_id": e.user_id,
                "external_product_id": e.external_product_id, "occurred_at": e.occurred_at.isoformat(),
                "context": e.context_json} for e in events],
        }
        event_count, product_count = len(events), len(products)
        user_count = len({e.user_id for e in events if e.user_id is not None})

        snapshot_id = uuid4()
        fingerprint = json.dumps(content, sort_keys=True, separators=(",", ":"))
        snapshot = DatasetSnapshot(
            id=snapshot_id,
            tenant_id=tenant_id,
            training_job_id=None,
            cutoff_at=cutoff,
            event_count=event_count,
            product_count=product_count,
            user_count=user_count,
            artifact_uri=f"postgres://dataset_snapshot_contents/{tenant_id}/{snapshot_id}",
            checksum=hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
            created_at=now,
        )
        self.db.add(snapshot)
        self.db.flush()
        self.db.add(DatasetSnapshotContent(snapshot_id=snapshot_id, tenant_id=tenant_id, content=content))
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        return DatasetSnapshotResource.model_validate(snapshot)

    def list_snapshots(self, tenant_id: UUID) -> list[DatasetSnapshotResource]:
        snapshots = (
            self.db.execute(
                select(DatasetSnapshot)
                .where(DatasetSnapshot.tenant_id == tenant_id)
                .order_by(DatasetSnapshot.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [DatasetSnapshotResource.model_validate(s) for s in snapshots]

    def get_snapshot(self, tenant_id: UUID, snapshot_id: UUID) -> DatasetSnapshotResource:
        snapshot = self.db.execute(
            select(DatasetSnapshot).where(
                DatasetSnapshot.tenant_id == tenant_id, DatasetSnapshot.id == snapshot_id
            )
        ).scalar_one_or_none()
        if not snapshot:
            raise ApiError(404, "resource_not_found", f"Dataset snapshot '{snapshot_id}' not found.")
        return DatasetSnapshotResource.model_validate(snapshot)


INTERACTION_COLUMNS = ("user_id", "item_id", "time")
MAX_INTERACTION_ROWS = 2_000_000


def _parse_interaction_log(raw_content: str) -> list[tuple[str, str, int]] | None:
    """Return ``(user, item, unix_time)`` rows for a ``user_id,item_id,time`` CSV.

    ``None`` means the content is not an interaction log (JSON, or a CSV with
    GraphRec ``event_id``/``external_id`` records), so the caller parses it the
    usual way. Malformed rows are rejected with a 422 that names the row.
    """
    content = raw_content.lstrip("﻿").strip()
    if not content or content[0] in "[{":
        return None
    reader = csv.reader(io.StringIO(content))
    try:
        header = [column.strip() for column in next(reader)]
    except StopIteration:
        return None
    columns = {name: index for index, name in enumerate(header)}
    if "timestamp" in columns and "time" not in columns:
        columns["time"] = columns["timestamp"]
    if not all(name in columns for name in INTERACTION_COLUMNS):
        return None
    if "event_id" in columns or "external_id" in columns:
        return None
    user_at, item_at, time_at = (columns[name] for name in INTERACTION_COLUMNS)
    rows: list[tuple[str, str, int]] = []
    for number, row in enumerate(reader, start=2):
        if not row or all(not value.strip() for value in row):
            continue
        try:
            user = row[user_at].strip()
            item = row[item_at].strip()
            moment = int(float(row[time_at].strip()))
        except (IndexError, ValueError) as exc:
            raise ApiError(
                422, "validation_failed", f"Interaction log row {number} is malformed"
            ) from exc
        if not user or not item or len(user) > 200 or len(item) > 100:
            raise ApiError(
                422, "validation_failed", f"Interaction log row {number} has an invalid user or item id"
            )
        rows.append((user, item, moment))
        if len(rows) > MAX_INTERACTION_ROWS:
            raise ApiError(413, "payload_too_large", "The interaction log has too many rows")
    if not rows:
        raise ApiError(422, "validation_failed", "The interaction log contains no rows")
    return rows


def _parse_dataset(raw_content: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    content = raw_content.strip()
    if not content:
        raise ApiError(422, "validation_failed", "The dataset file is empty")

    if content[0] in "[{":
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ApiError(422, "validation_failed", "The dataset file is not valid JSON") from exc
        if isinstance(parsed, dict):
            products = parsed.get("products") or []
            events = parsed.get("events") or []
        elif isinstance(parsed, list):
            products, events = _split_records(parsed)
        else:
            raise ApiError(422, "validation_failed", "The dataset JSON must be an object or array")
        if not isinstance(products, list) or not isinstance(events, list):
            raise ApiError(422, "validation_failed", "'products' and 'events' must be arrays")
        return products, events

    rows = list(csv.DictReader(io.StringIO(content)))
    return _split_records([_clean_csv_row(row) for row in rows])


def _split_records(records: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    products: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ApiError(422, "validation_failed", "Dataset records must be objects")
        if "event_id" in record:
            events.append(record)
        elif "external_id" in record:
            products.append(record)
        else:
            raise ApiError(
                422,
                "validation_failed",
                "Each record needs 'event_id' (event) or 'external_id' (product)",
            )
    return products, events


def _clean_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        if value is None or value == "":
            continue
        if key in {"context", "metadata"} and isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        cleaned[key.strip()] = value
    return cleaned
