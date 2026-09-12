from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from graphrec_core.auth.passwords import hash_password
from graphrec_core.auth.service import ROLE_SCOPES
from graphrec_core.database.models import TenantUser
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant

pytestmark = pytest.mark.integration

JSON = {"Accept": "application/json"}
MISSING = "00000000-0000-4000-8000-000000000000"
DATASET = (
    '{"products": [{"external_id": "scope-1", "title": "Scoped product"}],'
    ' "events": [{"event_id": "scope-e-1", "event_type": "view", "user_id": "u-1",'
    ' "external_product_id": "scope-1"}]}'
)

PRODUCT = {"external_id": "s-1", "title": "Scoped product"}
EVENT = {"event_id": "e-1", "event_type": "view", "user_id": "u-1", "external_product_id": "s-1"}
ITEM = {"external_product_id": "s-1", "position": 1}

# (method, path, valid JSON body, scopes the route requires). Bodies must be valid:
# request validation runs before the handler, so an invalid body would hide a 403.
DOMAIN_ROUTES: list[tuple[str, str, object, set[str]]] = [
    ("POST", "/v1/products:bulk-upsert", {"products": [PRODUCT]}, {"catalog:write"}),
    ("GET", "/v1/products", None, {"catalog:read"}),
    ("GET", "/v1/products/s-1", None, {"catalog:read"}),
    ("PUT", "/v1/products/s-1", PRODUCT, {"catalog:write"}),
    ("PATCH", "/v1/products/s-1", PRODUCT, {"catalog:write"}),
    ("POST", "/v1/products/s-1:disable", None, {"catalog:write"}),
    ("POST", "/v1/events", EVENT, {"events:write"}),
    ("POST", "/v1/events/batches", {"events": [{**EVENT, "event_id": "e-2"}]}, {"events:write"}),
    ("GET", "/v1/events/batches", None, {"events:read"}),
    ("GET", f"/v1/events/batches/{MISSING}", None, {"events:read"}),
    ("POST", "/v1/datasets/snapshots", {}, {"training:write"}),
    ("GET", "/v1/datasets/snapshots", None, {"training:read"}),
    ("GET", f"/v1/datasets/snapshots/{MISSING}", None, {"training:read"}),
    ("POST", "/v1/model-versions", {"version_tag": "scope-v1", "model_type": "simplified_dgsr"}, {"models:write"}),
    ("GET", "/v1/model-versions", None, {"models:read"}),
    ("GET", f"/v1/model-versions/{MISSING}", None, {"models:read"}),
    ("POST", f"/v1/model-versions/{MISSING}:activate", None, {"models:deploy"}),
    ("POST", f"/v1/model-versions/{MISSING}:archive", None, {"models:write"}),
    ("POST", f"/v1/models/{MISSING}:rollback", None, {"models:deploy"}),
    ("POST", "/v1/training-jobs", {"model_type": "simplified_dgsr"}, {"training:write"}),
    ("GET", "/v1/training-jobs", None, {"training:read"}),
    ("GET", "/v1/deployment", None, {"deployments:read"}),
    ("GET", "/v1/deployment/replicas", None, {"deployments:read"}),
    ("GET", "/v1/deployment/autoscaling", None, {"deployments:read"}),
    ("GET", "/v1/metrics/summary", None, {"metrics:read"}),
    ("POST", "/v1/recommendations", {"user_id": "u-1"}, {"recommendations:read"}),
    ("POST", "/v1/recommendations/session", {"user_id": "u-1"}, {"recommendations:read"}),
    ("POST", "/v1/feedback/impressions", {"event_id": "f-1", "request_id": "r-1", "items": [ITEM]}, {"events:write"}),
    ("POST", "/v1/feedback/clicks", {"event_id": "f-2", "request_id": "r-1", **ITEM}, {"events:write"}),
    ("POST", "/v1/feedback/conversions", {"event_id": "f-3", "request_id": "r-1", **ITEM}, {"events:write"}),
]


@pytest.fixture
def client() -> TestClient:
    # Handlers that pass the scope check may still fail on placeholder data (for
    # example a missing vector store); only the authorization outcome matters here.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def provision(client: TestClient, role: str) -> tuple[UUID, str]:
    suffix = uuid4().hex[:12]
    registration = client.post(
        "/v1/tenants",
        json={"name": f"Scope Tenant {suffix}", "admin_email": f"scope-admin-{suffix}@example.org"},
        headers={"Idempotency-Key": str(uuid4()), **JSON},
    )
    assert registration.status_code == 201
    tenant_id = UUID(registration.json()["id"])
    email = f"scope-{role}-{suffix}@example.org"
    password = "scope enforcement password"
    with SessionLocal() as session, session.begin():
        set_local_tenant(session, tenant_id)
        session.add(
            TenantUser(
                id=uuid4(),
                tenant_id=tenant_id,
                email=email,
                display_name="Scope Test User",
                credential_digest=hash_password(password),
                role=role,
                status="active",
                created_at=datetime.now(timezone.utc),
            )
        )
    login = client.post("/v1/auth/login", json={"email": email, "password": password}, headers=JSON)
    assert login.status_code == 200
    return tenant_id, login.json()["access_token"]


def call(client: TestClient, method: str, path: str, body: object, headers: dict[str, str]):
    return client.request(method, path, json=body, headers=headers)


def is_scope_denial(response) -> bool:
    return response.status_code == 403 and response.json()["error"]["code"] == "insufficient_scope"


def create_api_key(client: TestClient, token: str, scopes: list[str]) -> str:
    response = client.post(
        "/v1/api-keys",
        json={"name": f"scope-{uuid4().hex[:8]}", "scopes": scopes},
        headers={"Authorization": f"Bearer {token}", **JSON},
    )
    assert response.status_code == 201, response.text
    return response.json()["secret"]


@pytest.mark.parametrize("role", ["tenant_administrator", "tenant_developer"])
def test_bearer_tokens_only_reach_routes_their_role_grants(client: TestClient, role: str) -> None:
    _, token = provision(client, role)
    granted = set(ROLE_SCOPES[role])
    headers = {"Authorization": f"Bearer {token}", **JSON}

    for method, path, body, required in DOMAIN_ROUTES:
        response = call(client, method, path, body, headers)
        if required <= granted:
            assert not is_scope_denial(response), (role, method, path, response.text)
        else:
            assert is_scope_denial(response), (role, method, path, response.status_code)


def test_api_keys_are_limited_to_their_delegated_scopes(client: TestClient) -> None:
    _, admin_token = provision(client, "tenant_administrator")
    secret = create_api_key(client, admin_token, ["catalog:read"])
    headers = {"Authorization": f"ApiKey {secret}", **JSON}

    for method, path, body, required in DOMAIN_ROUTES:
        response = call(client, method, path, body, headers)
        if required <= {"catalog:read"}:
            assert not is_scope_denial(response), (method, path, response.text)
        else:
            assert is_scope_denial(response), (method, path, response.status_code)


def test_storefront_key_can_serve_recommendations_but_not_manage_models(client: TestClient) -> None:
    _, admin_token = provision(client, "tenant_administrator")
    secret = create_api_key(
        client, admin_token, ["catalog:read", "events:write", "recommendations:read"]
    )
    headers = {"Authorization": f"ApiKey {secret}", **JSON}

    recommended = client.post("/v1/recommendations", json={"user_id": "u-1"}, headers=headers)
    feedback = client.post(
        "/v1/feedback/clicks", json={"event_id": "c-1", "request_id": "r-1", **ITEM}, headers=headers
    )
    activate = client.post(f"/v1/model-versions/{MISSING}:activate", headers=headers)

    assert not is_scope_denial(recommended)
    assert not is_scope_denial(feedback)
    assert is_scope_denial(activate)


def test_dataset_upload_needs_both_catalog_and_event_write(client: TestClient) -> None:
    _, admin_token = provision(client, "tenant_administrator")
    catalog_only = create_api_key(client, admin_token, ["catalog:write"])
    both = create_api_key(client, admin_token, ["catalog:write", "events:write"])
    files = {"file": ("dataset.json", DATASET.encode(), "application/json")}

    denied = client.post(
        "/v1/datasets/upload", files=files, headers={"Authorization": f"ApiKey {catalog_only}", **JSON}
    )
    accepted = client.post(
        "/v1/datasets/upload", files=files, headers={"Authorization": f"ApiKey {both}", **JSON}
    )

    assert is_scope_denial(denied)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted_products"] == 1
