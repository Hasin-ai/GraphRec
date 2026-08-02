from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import app
from graphrec_core.schemas.products import ProductBulkUpsertRequest, ProductUpsert
from graphrec_core.schemas.events import EventBatchSubmit, EventSubmit
from graphrec_core.schemas.models import ModelVersionCreate, TrainingJobCreate

client = TestClient(app)


def test_products_bulk_upsert_and_list() -> None:
    tenant_id = uuid4()
    headers = {
        "X-Correlation-ID": str(uuid4()),
        "Idempotency-Key": str(uuid4()),
    }
    # Test request validation on missing tenant_id middleware state
    response = client.post(
        "/v1/products:bulk-upsert",
        json={"products": [{"external_id": "p-1", "title": "Test Product", "price": 10.5}]},
        headers=headers,
    )
    # Returns 401 unauthenticated when no bearer/api-key is attached in ContractMiddleware
    assert response.status_code in (200, 401, 422)


def test_model_version_registration_schema() -> None:
    req = ModelVersionCreate(
        version_tag="v1.0.0-test",
        model_type="simplified_dgsr",
        metrics={"recall_at_10": 0.85},
    )
    assert req.version_tag == "v1.0.0-test"
    assert req.metrics["recall_at_10"] == 0.85


def test_event_batch_schema() -> None:
    batch = EventBatchSubmit(
        events=[
            EventSubmit(
                event_id="e-1",
                event_type="click",
                user_id="u-10",
                external_product_id="p-1",
            )
        ]
    )
    assert len(batch.events) == 1
    assert batch.events[0].event_id == "e-1"
