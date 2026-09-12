from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from graphrec_core.catalog.service import CatalogService
from graphrec_core.database.models import CustomerEvent, DatasetSnapshot, Product
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError
from graphrec_core.events.service import EventService
from graphrec_core.schemas.datasets import (
    DatasetSnapshotCreate,
    DatasetSnapshotResource,
    DatasetUploadResponse,
)
from graphrec_core.schemas.events import EventBatchSubmit
from graphrec_core.schemas.products import ProductBulkUpsertRequest


class DatasetService:
    def __init__(self, db: Session):
        self.db = db

    def upload_dataset_content(self, tenant_id: UUID, raw_content: str) -> DatasetUploadResponse:
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

    def create_snapshot(
        self, tenant_id: UUID, payload: DatasetSnapshotCreate
    ) -> DatasetSnapshotResource:
        now = datetime.now(timezone.utc)
        cutoff = payload.cutoff_at or now
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)

        set_local_tenant(self.db, tenant_id)
        event_count, user_count = self.db.execute(
            select(
                func.count(CustomerEvent.id),
                func.count(func.distinct(CustomerEvent.user_id)),
            ).where(
                CustomerEvent.tenant_id == tenant_id,
                CustomerEvent.occurred_at <= cutoff,
            )
        ).one()
        product_count = self.db.execute(
            select(func.count(Product.id)).where(
                Product.tenant_id == tenant_id,
                Product.is_active == True,  # noqa: E712
            )
        ).scalar_one()

        snapshot_id = uuid4()
        fingerprint = f"{tenant_id}:{cutoff.isoformat()}:{event_count}:{product_count}:{user_count}"
        snapshot = DatasetSnapshot(
            id=snapshot_id,
            tenant_id=tenant_id,
            training_job_id=None,
            cutoff_at=cutoff,
            event_count=event_count,
            product_count=product_count,
            user_count=user_count,
            artifact_uri=f"rustfs://graphrec-datasets/{tenant_id}/{snapshot_id}.jsonl",
            checksum=hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
            created_at=now,
        )
        self.db.add(snapshot)
        self.db.commit()
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
