"""NR-NF-01 / ER-NF-02 / BRULE-02: every route against every kind of credential.

The route list is read from the running application, so a new route is swept
automatically; the PUBLIC set below is the only allowlist and is checked too.

* no credential            -> every non-public route answers 401;
* tenant credentials       -> every /v1/platform route (except operator sign-in) is refused;
* tenant B with A's ids    -> every route with a path parameter refuses A's resources,
                              and no response ever contains A's data;
* tenant B's list routes   -> never contain A's markers;
* A's resources are unchanged afterwards.
"""
from __future__ import annotations

import re
from uuid import uuid4

import pytest

from apps.api.main import app
from tests.integration.test_srs_acceptance import provision

pytestmark = pytest.mark.integration

PUBLIC = {
    ("GET", "/healthz"), ("GET", "/readyz"), ("GET", "/metrics"), ("GET", "/v1/meta"), ("GET", "/v1/plans"),
    ("POST", "/v1/tenants"), ("POST", "/v1/auth/login"), ("POST", "/v1/auth/setup-password"),
    ("POST", "/v1/auth/refresh"), ("POST", "/v1/auth/recover-password"), ("POST", "/v1/platform/auth/login"),
}
DOCS = {"/docs", "/docs/oauth2-redirect", "/openapi.json"}
BODIES = {  # valid bodies, so a refusal is about ownership rather than validation
    ("PATCH", "/v1/products/{external_id}"): {"title": "Overwritten by B"},
    ("PUT", "/v1/products/{external_id}"): None,  # filled per test
    ("PATCH", "/v1/tenant/users/{user_id}"): {"status": "locked"},
    ("POST", "/v1/api-keys/{key_id}/rotate"): {},
    ("POST", "/v1/model-versions/{version_id}:rollback"): {},
}
JSON = {"Accept": "application/json", "Content-Type": "application/json"}


def routes():
    for route in app.routes:
        for method in sorted(getattr(route, "methods", None) or ()):
            if method != "HEAD" and route.path not in DOCS:
                yield method, route.path


def call(client, method, path, headers, body=None):
    return client.request(method, path, headers={**JSON, **headers}, json={} if body is None else body)


@pytest.fixture(scope="module")
def world(client_module):
    client = client_module
    tag = uuid4().hex[:10]
    a_id, a = provision(client)
    b_id, b = provision(client)
    marker = f"isoA{tag}"
    sku = f"shared-{tag}"  # deliberately not the marker: B may own a product with the same name
    assert client.put(f"/v1/products/{sku}", json={"external_id": sku, "title": f"{marker} title"}, headers=a).status_code == 200
    sync = client.post("/v1/products:bulk-upsert", json={"products": [{"external_id": f"{marker}-2", "title": marker}]},
                       headers={**a, "Idempotency-Key": tag}).json()
    batch = client.post("/v1/events/batches", json={"events": [{"event_id": f"{marker}-e", "event_type": "view",
                        "user_id": f"{marker}-shopper", "external_product_id": sku}]}, headers=a).json()
    key = client.post("/v1/api-keys", json={"name": marker, "scopes": ["catalog:read"]}, headers=a).json()
    user = client.post("/v1/tenant/users", json={"email": f"{marker}@example.org"}, headers=a).json()
    snapshot = client.post("/v1/datasets/snapshots", json={}, headers=a).json()
    version = client.post("/v1/model-versions", json={"version_tag": marker, "model_type": "placeholder"}, headers=a).json()
    job = client.post("/v1/training-jobs", json={"request_id": marker, "configuration": {"mode": "placeholder"}}, headers=a)
    assert job.status_code == 200, job.text
    plan_request = client.post("/v1/subscription/requests", json={"plan_code": "basic", "message": marker}, headers=a)
    assert plan_request.status_code == 201, plan_request.text
    b_key = client.post("/v1/api-keys", json={"name": "b", "scopes": ["catalog:read", "events:write", "recommendations:read"]},
                        headers=b).json()["secret"]
    ids = {"external_id": sku, "sync_id": sync.get("sync_id"), "batch_id": batch.get("batch_id") or batch.get("id"),
           "key_id": key["id"], "user_id": user["id"], "snapshot_id": snapshot.get("id"), "version_id": version.get("id"),
           "model_id": version.get("id"), "job_id": job.json()["id"], "tenant_id": a_id, "operator_id": str(uuid4()),
           "plan_id": str(uuid4()), "request_id": plan_request.json()["id"]}
    assert all(ids.values()), ids  # every foreign id is a real resource of tenant A
    return {"client": client, "a": a, "b": b, "b_key": {"Authorization": f"ApiKey {b_key}"}, "ids": ids,
            "marker": marker, "sku": sku, "a_id": a_id}


@pytest.fixture(scope="module")
def client_module():
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        yield client


def test_public_allowlist_matches_real_routes():
    assert PUBLIC <= set(routes())


def test_nr_nf_01_every_non_public_route_requires_a_credential(world):
    client = world["client"]
    leaks = []
    for method, path in routes():
        if (method, path) in PUBLIC:
            continue
        concrete = re.sub(r"\{(\w+)\}", lambda m: str(world["ids"].get(m.group(1)) or uuid4()), path)
        response = call(client, method, concrete, {})
        # The multipart upload's content-type contract is checked before credentials;
        # either way nothing is processed.
        allowed = {400, 401, 415} if path == "/v1/datasets/upload" else {401}
        if response.status_code not in allowed:
            leaks.append(f"{method} {path} -> {response.status_code}")
    assert not leaks, leaks


def test_nr_nf_01_tenant_credentials_never_reach_platform_routes(world):
    client = world["client"]
    leaks = []
    for method, path in routes():
        if not path.startswith("/v1/platform") or (method, path) in PUBLIC:
            continue
        concrete = re.sub(r"\{(\w+)\}", lambda m: str(world["ids"].get(m.group(1)) or uuid4()), path)
        for credential in (world["b"], world["b_key"]):
            response = call(client, method, concrete, credential)
            if response.status_code not in (401, 403):
                leaks.append(f"{method} {path} -> {response.status_code}")
    assert not leaks, leaks


def test_er_nf_02_brule_02_tenant_b_cannot_reach_tenant_a_resources_by_id(world):
    client, ids, marker = world["client"], world["ids"], world["marker"]
    leaks = []
    for method, path in routes():
        if "{" not in path or path.startswith("/v1/platform"):
            continue
        concrete = re.sub(r"\{(\w+)\}", lambda m: str(ids[m.group(1)]), path)
        body = BODIES.get((method, path))
        if (method, path) == ("PUT", "/v1/products/{external_id}"):
            # External ids are tenant-local names: B may create its own product with the
            # same name, which must not touch A's product (checked below).
            body = {"external_id": ids["external_id"], "title": "B's own product"}
        for credential in (world["b"], world["b_key"]):
            response = call(client, method, concrete, credential, body)
            if marker in response.text:
                leaks.append(f"{method} {path}: response contains tenant A data")
            if response.status_code < 300 and (method, path) != ("PUT", "/v1/products/{external_id}") \
                    and not (path == "/v1/products/{external_id}" and method in {"GET", "PATCH"} and credential is world["b"]
                             and response.json().get("title") == "B's own product") \
                    and not (path == "/v1/products/{external_id}:disable" and "B's own product" in response.text):
                leaks.append(f"{method} {path} -> {response.status_code}")
    assert not leaks, leaks
    # A's resources are untouched by everything B did.
    a = world["a"]
    product = client.get(f"/v1/products/{ids['external_id']}", headers=a).json()
    assert product["title"] == f"{marker} title" and product["is_active"] is True
    member = client.get(f"/v1/tenant/users/{ids['user_id']}", headers=a).json()
    assert member["status"] == "invited"
    assert client.get(f"/v1/api-keys/{ids['key_id']}", headers=a).json()["status"] == "active"


def test_nr_nf_01_tenant_b_lists_never_contain_tenant_a_data(world):
    client, marker = world["client"], world["marker"]
    leaks = []
    for method, path in routes():
        if method != "GET" or "{" in path or path.startswith("/v1/platform") or (method, path) in PUBLIC:
            continue
        for credential in (world["b"], world["b_key"]):
            response = client.get(path, headers={"Accept": "application/json", **credential})
            if marker in response.text or world["a_id"] in response.text:
                leaks.append(f"GET {path}")
    assert not leaks, leaks
