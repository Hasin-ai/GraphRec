from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from apps.api.main import app
from graphrec_core.auth.passwords import hash_password
from graphrec_core.database.models import CustomerEvent, Product, TenantUser
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.settings import Settings, get_settings

pytestmark = pytest.mark.integration

PLATFORM_TOKEN = "integration-platform-administrator-token-0123456789"
JSON = {"Accept": "application/json"}


def provision_developer(client: TestClient) -> tuple[UUID, str]:
    suffix = uuid4().hex[:12]
    registration = client.post(
        "/v1/tenants",
        json={"name": f"Isolation Tenant {suffix}", "admin_email": f"invited-{suffix}@example.org"},
        headers={"Idempotency-Key": str(uuid4()), **JSON},
    )
    assert registration.status_code == 201
    tenant_id = UUID(registration.json()["id"])
    email = f"dev-{suffix}@example.org"
    password = "isolation test password"
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.add(
            TenantUser(
                id=uuid4(),
                tenant_id=tenant_id,
                email=email,
                display_name="Isolation Developer",
                credential_digest=hash_password(password),
                role="tenant_developer",
                status="active",
                created_at=datetime.now(timezone.utc),
            )
        )
    login = client.post("/v1/auth/login", json={"email": email, "password": password}, headers=JSON)
    assert login.status_code == 200
    return tenant_id, login.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **JSON}


@pytest.fixture
def platform_client():
    app.dependency_overrides[get_settings] = lambda: Settings(platform_admin_token=PLATFORM_TOKEN)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_products_are_invisible_across_tenants(client: TestClient) -> None:
    tenant_a, token_a = provision_developer(client)
    tenant_b, token_b = provision_developer(client)
    external_id = f"sku-{uuid4().hex[:8]}"

    created = client.post(
        "/v1/products:bulk-upsert",
        json={"products": [{"external_id": external_id, "title": "Only for A", "price": 9.5}]},
        headers=bearer(token_a),
    )
    assert created.status_code == 200
    assert created.json()["created_count"] == 1

    assert client.get(f"/v1/products/{external_id}", headers=bearer(token_a)).status_code == 200
    assert client.get(f"/v1/products/{external_id}", headers=bearer(token_b)).status_code == 404
    listed_for_b = client.get("/v1/products", headers=bearer(token_b))
    assert listed_for_b.status_code == 200
    assert listed_for_b.json()["items"] == []

    with SessionLocal() as session, session.begin():
        assert session.scalar(select(func.count(Product.id))) == 0
        set_local_tenant(session, tenant_b)
        assert session.scalar(select(func.count(Product.id))) == 0
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_a)
        assert session.scalar(select(func.count(Product.id))) == 1


def test_row_level_security_blocks_mismatched_tenant_writes(client: TestClient) -> None:
    tenant_a, _ = provision_developer(client)
    tenant_b, _ = provision_developer(client)
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        session.begin()
        set_local_tenant(session, tenant_a)
        session.add(
            CustomerEvent(
                id=uuid4(),
                tenant_id=tenant_b,
                event_id=f"evt-{uuid4().hex[:8]}",
                event_type="view",
                occurred_at=now,
                created_at=now,
            )
        )
        with pytest.raises(DBAPIError):
            session.flush()
        session.rollback()


def test_dataset_upload_creates_snapshot_for_caller_only(client: TestClient) -> None:
    _, token_a = provision_developer(client)
    _, token_b = provision_developer(client)
    dataset = (
        '{"products": [{"external_id": "ds-1", "title": "Dataset product"}],'
        ' "events": [{"event_id": "ds-e-1", "event_type": "view", "user_id": "u-1",'
        ' "external_product_id": "ds-1"}]}'
    )
    upload = client.post(
        "/v1/datasets/upload",
        files={"file": ("dataset.json", dataset.encode(), "application/json")},
        headers=bearer(token_a),
    )
    assert upload.status_code == 200, upload.text
    body = upload.json()
    assert body["accepted_products"] == 1
    assert body["accepted_events"] == 1
    assert body["dataset_snapshot"]["product_count"] == 1
    assert body["dataset_snapshot"]["event_count"] == 1
    assert body["dataset_snapshot"]["user_count"] == 1

    snapshot_id = body["dataset_snapshot"]["id"]
    assert client.get(f"/v1/datasets/snapshots/{snapshot_id}", headers=bearer(token_a)).status_code == 200
    assert client.get(f"/v1/datasets/snapshots/{snapshot_id}", headers=bearer(token_b)).status_code == 404


def test_platform_administrator_manages_tenants_across_boundaries(platform_client: TestClient) -> None:
    tenant_id, token = provision_developer(platform_client)
    admin = {"Authorization": f"Bearer {PLATFORM_TOKEN}", **JSON}

    listing = platform_client.get("/v1/platform/tenants", headers=admin)
    assert listing.status_code == 200
    assert str(tenant_id) in {item["id"] for item in listing.json()["items"]}

    missing = platform_client.get(f"/v1/platform/tenants/{uuid4()}", headers=admin)
    assert missing.status_code == 404

    suspended = platform_client.post(
        f"/v1/platform/tenants/{tenant_id}/status", json={"status": "suspended"}, headers=admin
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert platform_client.get("/v1/products", headers=bearer(token)).status_code == 401

    invalid = platform_client.post(
        f"/v1/platform/tenants/{tenant_id}/status", json={"status": "nonsense"}, headers=admin
    )
    assert invalid.status_code == 422

    restored = platform_client.post(
        f"/v1/platform/tenants/{tenant_id}/status", json={"status": "active"}, headers=admin
    )
    assert restored.status_code == 200
    assert platform_client.get("/v1/products", headers=bearer(token)).status_code == 200

    audit = platform_client.get("/v1/platform/audit", headers=admin)
    assert audit.status_code == 200
    status_changes = [
        item
        for item in audit.json()["items"]
        if item["tenant_id"] == str(tenant_id) and item["action_type"] == "tenant.status_changed"
    ]
    assert len(status_changes) == 2
    assert all(item["actor_type"] == "platform_administrator" for item in status_changes)

    quota = platform_client.post(
        f"/v1/platform/tenants/{tenant_id}/quotas",
        json={"overrides": {"stored_products": 12}},
        headers=admin,
    )
    assert quota.status_code == 200
    assert quota.json()["overrides"] == {"stored_products": 12}

    failures = platform_client.get("/v1/platform/failures", headers=admin)
    assert failures.status_code == 200

    status = platform_client.get("/v1/platform/status", headers=admin)
    assert status.status_code == 200
    assert status.json()["database"] == "connected"
