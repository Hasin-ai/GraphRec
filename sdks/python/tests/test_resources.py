"""Every route in ``ROUTES`` is exercised through its public SDK method."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

import graphrec_sdk as g

from . import conftest as fx
from .conftest import MockAPI, make_client


@dataclass
class Case:
    route: str
    path: str
    response: Any
    call: Callable[[g.GraphRec], Any]
    body: Optional[Callable[[Any], None]] = None
    check: Optional[Callable[[Any], None]] = None
    client_kwargs: Optional[Dict[str, Any]] = None


BEARER = {"api_key": None, "access_token": "jwt"}
PLATFORM = {"api_key": None, "access_token": "platform-admin-token-0123456789abcdef"}
EXPIRES = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _eq(expected: Dict[str, Any]) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        assert body == expected

    return check


def _has(**expected: Any) -> Callable[[Any], None]:
    def check(body: Any) -> None:
        for key, value in expected.items():
            assert body[key] == value, key

    return check


CASES: List[Case] = [
    Case(
        "health.check",
        "/healthz",
        {"status": "ok"},
        lambda c: c.health(),
        check=lambda r: r == {"status": "ok"},
    ),
    Case(
        "tenants.register",
        "/v1/tenants",
        {
            "id": fx.UUID_A,
            "name": "Shop",
            "status": "active",
            "created_at": fx.NOW,
            "administrator_email": "o@shop.test",
            "next_step": "setup",
            "setup_token": "one-time-token",
            "setup_token_expires_at": fx.NOW,
        },
        lambda c: c.tenants.register(name="Shop", admin_email="o@shop.test"),
        body=_eq({"name": "Shop", "admin_email": "o@shop.test"}),
        check=lambda r: r.setup_token == "one-time-token" and r.setup_token_expires_at is not None,
    ),
    Case(
        "auth.login",
        "/v1/auth/login",
        fx.tokens(),
        lambda c: c.auth.login(email="a@shop.test", password="pw"),
        body=_eq({"email": "a@shop.test", "password": "pw"}),
        check=lambda r: r.user_role == "tenant_administrator",
    ),
    Case(
        "auth.setup_password",
        "/v1/auth/setup-password",
        fx.tokens(),
        lambda c: c.auth.setup_password(setup_token="one-time-token", password="long-password"),
        body=_eq({"setup_token": "one-time-token", "password": "long-password"}),
    ),
    Case(
        "api_keys.list",
        "/v1/api-keys",
        {"items": [fx.api_key()]},
        lambda c: c.api_keys.list(),
        check=lambda r: r[0].is_active,
        client_kwargs=BEARER,
    ),
    Case(
        "api_keys.get",
        f"/v1/api-keys/{fx.UUID_A}",
        fx.api_key(),
        lambda c: c.api_keys.get(fx.UUID_A),
        client_kwargs=BEARER,
    ),
    Case(
        "api_keys.create",
        "/v1/api-keys",
        fx.api_key(secret=True),
        lambda c: c.api_keys.create(
            name="storefront", scopes=g.STOREFRONT_KEY_SCOPES, expires_at=EXPIRES
        ),
        body=_eq(
            {
                "name": "storefront",
                "scopes": [
                    "catalog:read",
                    "catalog:write",
                    "events:read",
                    "events:write",
                    "recommendations:read",
                ],
                "expires_at": "2030-01-01T00:00:00+00:00",
            }
        ),
        check=lambda r: r.secret.startswith("gr_live_") and "***" in repr(r),
        client_kwargs=BEARER,
    ),
    Case(
        "api_keys.rotate",
        f"/v1/api-keys/{fx.UUID_A}/rotate",
        fx.api_key(secret=True),
        lambda c: c.api_keys.rotate(fx.UUID_A, reason="scheduled", grace_period_seconds=3600),
        body=_eq({"grace_period_seconds": 3600, "reason": "scheduled"}),
        client_kwargs=BEARER,
    ),
    Case(
        "api_keys.revoke",
        f"/v1/api-keys/{fx.UUID_A}",
        fx.api_key(status="revoked", revoked_at=fx.NOW),
        lambda c: c.api_keys.revoke(fx.UUID_A),
        check=lambda r: r.status == "revoked",
        client_kwargs=BEARER,
    ),
    Case(
        "subscription.get",
        "/v1/subscription",
        {
            "plan_code": "basic",
            "status": "active",
            "period_start": fx.NOW,
            "period_end": "2026-10-01T00:00:00Z",
            "limits": {"accepted_events": 500000},
            "project_defaults": True,
        },
        lambda c: c.subscription.get(),
        check=lambda r: r.limits["accepted_events"] == 500000,
    ),
    Case(
        "usage.get",
        "/v1/usage",
        {
            "period_start": fx.NOW,
            "period_end": "2026-10-01T00:00:00Z",
            "reset_at": "2026-10-01T00:00:00Z",
            "dimensions": [],
            "last_reconciled_at": fx.NOW,
            "project_defaults": False,
        },
        lambda c: c.usage.get(),
    ),
    Case(
        "products.bulk_upsert",
        "/v1/products:bulk-upsert",
        fx.bulk_result(created=2),
        lambda c: c.products.bulk_upsert(
            [
                {"external_id": "a", "title": "A"},
                g.ProductInput(external_id="b", title="B", price="5"),
            ]
        ),
        body=lambda b: (
            [p["external_id"] for p in b["products"]] == ["a", "b"]
            and b["products"][1]["price"] == "5"
        ),
        check=lambda r: r.created_count == 2 and r.request_count == 1,
    ),
    Case(
        "products.list",
        "/v1/products",
        {"items": [fx.product()], "total": 1},
        lambda c: c.products.list(),
        check=lambda r: r.total == 1 and r[0].price == Decimal("49.90"),
    ),
    Case("products.get", "/v1/products/sku-1", fx.product(), lambda c: c.products.get("sku-1")),
    Case(
        "products.upsert",
        "/v1/products/sku-1",
        fx.product(),
        lambda c: c.products.upsert(g.ProductInput(external_id="sku-1", title="Linen shirt")),
        body=_has(external_id="sku-1", title="Linen shirt", price="0.00", is_active=True),
    ),
    Case(
        "products.disable",
        "/v1/products/sku-1:disable",
        fx.product(is_active=False),
        lambda c: c.products.disable("sku-1"),
        body=lambda b: b is None,
    ),
    Case(
        "events.create",
        "/v1/events",
        {"event_id": "evt-1", "accepted": True, "duplicate": False, "received_at": fx.NOW},
        lambda c: c.events.create(
            g.EventType.VIEW,
            user_id="u1",
            product_id="sku-1",
            event_id="evt-1",
            context={"page": "pdp"},
        ),
        body=_has(
            event_id="evt-1",
            event_type="view",
            user_id="u1",
            external_product_id="sku-1",
            context={"page": "pdp"},
        ),
    ),
    Case(
        "events.create_batch",
        "/v1/events/batches",
        fx.event_batch(accepted=2),
        lambda c: c.events.create_batch(
            [
                {"event_type": "click", "event_id": "e1"},
                g.EventInput(event_type="purchase", event_id="e2"),
            ]
        ),
        body=lambda b: [e["event_id"] for e in b["events"]] == ["e1", "e2"],
        check=lambda r: r.accepted_count == 2 and len(r.batches) == 1,
    ),
    Case(
        "events.list_batches",
        "/v1/events/batches",
        [fx.event_batch()],
        lambda c: c.events.list_batches(),
        check=lambda r: len(r) == 1,
    ),
    Case(
        "events.get_batch",
        f"/v1/events/batches/{fx.UUID_A}",
        fx.event_batch(),
        lambda c: c.events.get_batch(fx.UUID_A),
    ),
    Case(
        "datasets.upload",
        "/v1/datasets/upload",
        {"accepted_events": 1, "accepted_products": 1, "dataset_snapshot": fx.snapshot()},
        lambda c: c.datasets.upload(("export.csv", b"external_id,title\nsku-1,Shirt\n")),
        check=lambda r: r.dataset_snapshot.event_count == 10,
    ),
    Case(
        "datasets.create_snapshot",
        "/v1/datasets/snapshots",
        fx.snapshot(),
        lambda c: c.datasets.create_snapshot(cutoff_at=EXPIRES, description="weekly"),
        body=_eq({"cutoff_at": "2030-01-01T00:00:00+00:00", "description": "weekly"}),
    ),
    Case(
        "datasets.list_snapshots",
        "/v1/datasets/snapshots",
        {"items": [fx.snapshot()]},
        lambda c: c.datasets.list_snapshots(),
    ),
    Case(
        "datasets.get_snapshot",
        f"/v1/datasets/snapshots/{fx.UUID_A}",
        fx.snapshot(),
        lambda c: c.datasets.get_snapshot(fx.UUID_A),
    ),
    Case(
        "model_versions.create",
        "/v1/model-versions",
        fx.model_version(),
        lambda c: c.model_versions.create(version_tag="v1", metrics={"ndcg_at_10": 0.7}),
        body=_eq(
            {"version_tag": "v1", "model_type": "simplified_dgsr", "metrics": {"ndcg_at_10": 0.7}}
        ),
    ),
    Case(
        "model_versions.list",
        "/v1/model-versions",
        {"items": [fx.model_version("active"), fx.model_version("retired", fx.UUID_A)]},
        lambda c: c.model_versions.list(),
        check=lambda r: r.active is not None and str(r.active.id) == fx.UUID_B,
    ),
    Case(
        "model_versions.get",
        f"/v1/model-versions/{fx.UUID_B}",
        fx.model_version(),
        lambda c: c.model_versions.get(fx.UUID_B),
    ),
    Case(
        "model_versions.activate",
        f"/v1/model-versions/{fx.UUID_B}:activate",
        fx.model_version("active"),
        lambda c: c.model_versions.activate(fx.UUID_B),
        check=lambda r: r.is_active,
    ),
    Case(
        "model_versions.archive",
        f"/v1/model-versions/{fx.UUID_B}:archive",
        fx.model_version("archived"),
        lambda c: c.model_versions.archive(fx.UUID_B),
    ),
    Case(
        "model_versions.rollback",
        f"/v1/models/{fx.UUID_B}:rollback",
        fx.model_version("active"),
        lambda c: c.model_versions.rollback(fx.UUID_B),
    ),
    Case(
        "training_jobs.create",
        "/v1/training-jobs",
        fx.training_job(),
        lambda c: c.training_jobs.create(
            dataset_snapshot_id=fx.UUID_A, configuration={"epochs": 10}
        ),
        body=_eq(
            {
                "model_type": "simplified_dgsr",
                "dataset_snapshot_id": fx.UUID_A,
                "configuration": {"epochs": 10},
            }
        ),
        check=lambda r: r.succeeded and r.is_terminal,
    ),
    Case(
        "training_jobs.list",
        "/v1/training-jobs",
        {"items": [fx.training_job()]},
        lambda c: c.training_jobs.list(),
    ),
    Case(
        "deployment.get",
        "/v1/deployment",
        {
            "status": "available",
            "active_model_version_id": fx.UUID_B,
            "desired_model_version_id": fx.UUID_B,
            "desired_replicas": 1,
            "current_replicas": 1,
            "ready_replicas": 1,
            "last_transition_at": fx.NOW,
            "failure_reason": None,
        },
        lambda c: c.deployment.get(),
    ),
    Case(
        "deployment.replicas",
        "/v1/deployment/replicas",
        {
            "desired_replicas": 1,
            "current_replicas": 1,
            "ready_replicas": 1,
            "replicas": [
                {
                    "id": "replica-1",
                    "model_version_id": None,
                    "status": "idle",
                    "ready": False,
                    "started_at": fx.NOW,
                }
            ],
        },
        lambda c: c.deployment.replicas(),
        check=lambda r: r.replicas[0].id == "replica-1",
    ),
    Case(
        "deployment.autoscaling",
        "/v1/deployment/autoscaling",
        {
            "min_replicas": 1,
            "max_replicas": 2,
            "cpu_target_percent": 65,
            "inflight_target": None,
            "desired_replicas": 1,
            "ready_replicas": 1,
            "capacity_blocked": False,
            "metrics_available": True,
            "recent_actions": [{"reason": "cpu_target_nominal"}],
        },
        lambda c: c.deployment.autoscaling(),
    ),
    Case(
        "metrics.summary",
        "/v1/metrics/summary",
        {
            "window_start": fx.NOW,
            "window_end": fx.NOW,
            "request_rate": 14.5,
            "error_rate": 0.001,
            "fallback_rate": 0.02,
            "p95_latency_ms": 185,
            "active_model_version_id": None,
            "desired_replicas": 1,
            "ready_replicas": 1,
            "quality": {
                "hit_at_10": 0.88,
                "ndcg_at_10": 0.79,
                "retrieval_recall_at_k": 0.91,
                "catalog_coverage": 0.74,
                "intra_list_diversity": 0.68,
                "training_loss": 0.14,
                "validation_loss": 0.18,
                "recorded_at": fx.NOW,
            },
        },
        lambda c: c.metrics.summary(),
        check=lambda r: r.quality is not None and r.quality.ndcg_at_10 == 0.79,
    ),
    Case(
        "recommendations.get",
        "/v1/recommendations",
        fx.recommendations(),
        lambda c: c.recommendations.get(
            user_id="u1", top_n=3, exclude_product_ids=["sku-9", "sku-9"]
        ),
        body=_eq({"top_n": 3, "context": {}, "user_id": "u1", "exclude_product_ids": ["sku-9"]}),
        check=lambda r: r.product_ids == ["sku-1", "sku-2", "sku-3"] and r.is_personalized,
    ),
    Case(
        "recommendations.for_session",
        "/v1/recommendations/session",
        fx.recommendations(),
        lambda c: c.recommendations.for_session(
            "sess-1", recent_product_ids=["sku-5"], context={"page": "cart"}
        ),
        body=_eq(
            {
                "top_n": 10,
                "context": {
                    "page": "cart",
                    "session_id": "sess-1",
                    "recent_product_ids": ["sku-5"],
                },
            }
        ),
    ),
    Case(
        "feedback.impression",
        "/v1/feedback/impressions",
        fx.feedback("impression"),
        lambda c: c.feedback.impression("rec-1", items=["sku-1", "sku-2"], event_id="imp-1"),
        body=_has(
            event_id="imp-1",
            request_id="rec-1",
            items=[
                {"external_product_id": "sku-1", "position": 1},
                {"external_product_id": "sku-2", "position": 2},
            ],
        ),
    ),
    Case(
        "feedback.click",
        "/v1/feedback/clicks",
        fx.feedback("click"),
        lambda c: c.feedback.click("rec-1", "sku-2", position=2, impression_event_id="imp-1"),
        body=_has(
            request_id="rec-1", external_product_id="sku-2", position=2, impression_event_id="imp-1"
        ),
    ),
    Case(
        "feedback.conversion",
        "/v1/feedback/conversions",
        fx.feedback("conversion"),
        lambda c: c.feedback.conversion("rec-1", "sku-2", value=49.9),
        body=lambda b: b["value"] == "49.9" and "position" not in b,
    ),
    Case(
        "platform.list_tenants",
        "/v1/platform/tenants",
        {
            "items": [
                {
                    "id": fx.UUID_A,
                    "slug": "shop",
                    "name": "Shop",
                    "status": "active",
                    "created_at": fx.NOW,
                }
            ]
        },
        lambda c: c.platform.list_tenants(),
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.get_tenant",
        f"/v1/platform/tenants/{fx.UUID_A}",
        {"id": fx.UUID_A, "slug": "shop", "name": "Shop", "status": "active", "created_at": fx.NOW},
        lambda c: c.platform.get_tenant(fx.UUID_A),
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.set_tenant_status",
        f"/v1/platform/tenants/{fx.UUID_A}/status",
        {
            "id": fx.UUID_A,
            "slug": "shop",
            "name": "Shop",
            "status": "suspended",
            "created_at": fx.NOW,
        },
        lambda c: c.platform.set_tenant_status(fx.UUID_A, g.TenantStatus.SUSPENDED),
        body=_eq({"status": "suspended"}),
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.list_plans",
        "/v1/platform/plans",
        [
            {
                "id": fx.UUID_A,
                "code": "free",
                "name": "Free Tier",
                "limits": {"accepted_events": 50000},
                "is_active": True,
            }
        ],
        lambda c: c.platform.list_plans(),
        check=lambda r: r[0].code == "free",
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.set_quota_override",
        f"/v1/platform/tenants/{fx.UUID_A}/quotas",
        {"limits": {"accepted_events": 50000}, "overrides": {"accepted_events": 1000000}},
        lambda c: c.platform.set_quota_override(
            fx.UUID_A, overrides={"accepted_events": 1_000_000}
        ),
        body=_eq({"overrides": {"accepted_events": 1000000}}),
        check=lambda r: r.overrides["accepted_events"] == 1_000_000,
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.list_failures",
        "/v1/platform/failures",
        {
            "items": [
                {
                    "id": fx.UUID_A,
                    "tenant_id": None,
                    "event_type": "login_denied",
                    "severity": "warning",
                    "sanitized_detail": {},
                    "occurred_at": fx.NOW,
                }
            ]
        },
        lambda c: c.platform.list_failures(),
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.list_audit_logs",
        "/v1/platform/audit",
        {
            "items": [
                {
                    "id": fx.UUID_A,
                    "tenant_id": fx.UUID_B,
                    "actor_type": "tenant_user",
                    "action_type": "authentication",
                    "resource_type": "refresh_session",
                    "outcome": "succeeded",
                    "occurred_at": fx.NOW,
                }
            ]
        },
        lambda c: c.platform.list_audit_logs(),
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.status",
        "/v1/platform/status",
        {"status": "healthy", "database": "connected"},
        lambda c: c.platform.status(),
        client_kwargs=PLATFORM,
    ),
]


def test_every_route_has_a_case() -> None:
    covered = {case.route for case in CASES} | {
        "products.update"
    }  # update: see test_products_update
    assert covered == set(g.ROUTES)


@pytest.mark.parametrize("case", CASES, ids=[case.route for case in CASES])
def test_route(case: Case, api: MockAPI, sleeps: List[float]) -> None:
    route = g.ROUTES[case.route]
    api.on(route.method, re.escape(case.path), case.response)
    with make_client(api, sleeps, **(case.client_kwargs or {})) as client:
        result = case.call(client)
    assert [f"{c.method} {c.path}" for c in api.calls] == [f"{route.method} {case.path}"]
    sent = api.last()
    if route.body == "json":
        assert sent.headers["Content-Type"] == "application/json"
        if case.body is not None:
            outcome = case.body(sent.json())
            assert outcome in (None, True)
    elif route.body == "multipart":
        assert sent.headers["Content-Type"].startswith("multipart/form-data; boundary=")
        assert b'filename="export.csv"' in sent.request.content
        assert b"Content-Type: text/csv" in sent.request.content
    if route.auth == "none":
        assert "Authorization" not in sent.headers
    if case.check is not None:
        assert case.check(result) in (None, True)


def test_products_update_merges_current_state(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", "/v1/products/sku-1", fx.product(metadata={"brand": "Acme"}))
    api.on("PATCH", "/v1/products/sku-1", lambda req: fx.product(price="39.90"))
    with make_client(api, sleeps) as client:
        updated = client.products.update(
            "sku-1", price="39.90", availability_status=g.AvailabilityStatus.OUT_OF_STOCK
        )
    assert api.paths() == ["GET /v1/products/sku-1", "PATCH /v1/products/sku-1"]
    assert api.last().json() == {
        "external_id": "sku-1",
        "title": "Linen shirt",
        "price": "39.90",
        "category": "apparel",
        "is_active": True,
        "availability_status": "out_of_stock",
        "metadata": {"brand": "Acme"},
    }
    assert str(updated.price) == "39.90"


def test_dataset_upload_from_path(api: MockAPI, sleeps: List[float], tmp_path: Path) -> None:
    export = tmp_path / "catalog.json"
    export.write_text('[{"external_id": "sku-1", "title": "Shirt"}]', encoding="utf-8")
    api.on(
        "POST",
        "/v1/datasets/upload",
        {"accepted_events": 0, "accepted_products": 1, "dataset_snapshot": fx.snapshot()},
    )
    with make_client(api, sleeps) as client:
        client.datasets.upload(export)
    assert b'filename="catalog.json"' in api.last().request.content
    assert b"Content-Type: application/json" in api.last().request.content


def test_training_job_wait_polls_until_terminal(
    api: MockAPI, sleeps: List[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    api.queue(
        "GET",
        "/v1/training-jobs",
        {"items": [fx.training_job("training")]},
        {"items": [fx.training_job("succeeded")]},
    )
    monkeypatch.setattr("graphrec_sdk.resources.ml.time.sleep", lambda _s: None)
    with make_client(api, sleeps) as client:
        job = client.training_jobs.wait(fx.UUID_A, poll_interval=0.01, timeout=5)
    assert job.succeeded and len(api.calls) == 2


def test_training_job_wait_times_out(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", "/v1/training-jobs", {"items": [fx.training_job("training")]})
    with make_client(api, sleeps) as client, pytest.raises(g.WaitTimeoutError):
        client.training_jobs.wait(fx.UUID_A, poll_interval=0.01, timeout=0.02)


def test_get_active_version_returns_none_without_active(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", "/v1/model-versions", {"items": [fx.model_version("eligible")]})
    with make_client(api, sleeps) as client:
        assert client.model_versions.get_active() is None


def test_feedback_from_recommendations_object(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/recommendations", fx.recommendations())
    api.on("POST", "/v1/feedback/impressions", fx.feedback("impression", "imp-9"))
    api.on("POST", "/v1/feedback/clicks", fx.feedback("click"))
    with make_client(api, sleeps) as client:
        recs = client.recommendations.get(user_id="u1")
        client.feedback.impression(recs)
        assert api.last().json()["items"][2] == {"external_product_id": "sku-3", "position": 3}
        client.feedback.click(recs, "sku-3")
        assert api.last().json()["position"] == 3
        with pytest.raises(g.InputValidationError):
            client.feedback.click(recs, "sku-404")
        with pytest.raises(g.InputValidationError):
            client.feedback.click("rec-1", "sku-1")
        with pytest.raises(g.InputValidationError):
            client.feedback.impression("rec-1")


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.recommendations.get(top_n=0),
        lambda c: c.recommendations.get(top_n=101),
        lambda c: c.recommendations.get(exclude_product_ids=[str(i) for i in range(201)]),
        lambda c: c.products.upsert({"external_id": "", "title": "x"}),
        lambda c: c.products.upsert({"external_id": "a", "title": "x", "price": -1}),
        lambda c: c.products.upsert({"external_id": "a", "title": "x", "colour": "red"}),
        lambda c: c.events.create("x" * 49),
        lambda c: c.feedback.conversion("rec-1", "sku-1", value=-5),
        lambda c: c.model_versions.create(version_tag=""),
        lambda c: c.recommendations.for_session(""),
    ],
)
def test_client_side_validation_sends_nothing(
    call: Callable[[g.GraphRec], Any], api: MockAPI, sleeps: List[float]
) -> None:
    with make_client(api, sleeps) as client, pytest.raises(g.InputValidationError):
        call(client)
    assert api.calls == []


def test_api_key_inputs_are_validated(api: MockAPI, sleeps: List[float]) -> None:
    with make_client(api, sleeps, **BEARER) as client:
        with pytest.raises(g.InputValidationError):
            client.api_keys.create(name="k", scopes=[])
        with pytest.raises(g.InputValidationError):
            client.api_keys.create(name="k", scopes=["catalog:read", g.Scope.CATALOG_READ])
        with pytest.raises(g.InputValidationError):
            client.api_keys.create(
                name="k", scopes=["catalog:read"], expires_at=datetime(2030, 1, 1)
            )
        with pytest.raises(g.InputValidationError):
            client.api_keys.rotate(fx.UUID_A, reason="x", grace_period_seconds=90_000)
    assert api.calls == []


def test_setup_password_sends_optional_email_and_maps_rejection(
    api: MockAPI, sleeps: List[float]
) -> None:
    api.queue(
        "POST",
        "/v1/auth/setup-password",
        fx.tokens(),
        fx.error(
            401, "invalid_setup_token", "The setup token is invalid, expired, or already used"
        ),
    )
    with make_client(api, sleeps, api_key=None) as client:
        client.auth.setup_password(setup_token="tok", password="long-password", email="a@shop.test")
        assert api.last().json() == {
            "setup_token": "tok",
            "password": "long-password",
            "email": "a@shop.test",
        }
        with pytest.raises(g.AuthenticationError) as caught:
            client.auth.setup_password(setup_token="tok", password="long-password")
    assert caught.value.code == "invalid_setup_token"
    assert "Authorization" not in api.last().headers
    assert len(api.calls) == 2  # a rejected token is never retried


def test_replayed_registration_has_no_setup_token(api: MockAPI, sleeps: List[float]) -> None:
    api.on(
        "POST",
        "/v1/tenants",
        {
            "id": fx.UUID_A,
            "name": "Shop",
            "status": "active",
            "created_at": fx.NOW,
            "administrator_email": "o@shop.test",
            "next_step": "setup",
            "setup_token": None,
            "setup_token_expires_at": None,
        },
    )
    with make_client(api, sleeps) as client:
        tenant = client.tenants.register(name="Shop", admin_email="o@shop.test")
    assert tenant.setup_token is None and tenant.setup_token_expires_at is None


def test_required_scopes() -> None:
    assert g.ROUTES["datasets.upload"].required_scopes == ("catalog:write", "events:write")
    assert g.ROUTES["products.list"].required_scopes == ("catalog:read",)
    assert g.ROUTES["health.check"].required_scopes == ()
    tenant_routes = [
        route
        for route in g.ROUTES.values()
        if route.auth != "none" and not route.key.startswith("platform.")
    ]
    assert tenant_routes and all(route.scope_enforced for route in tenant_routes)
    for role, scopes in g.ROLE_SCOPES.items():
        assert g.DELEGATABLE_SCOPES[role] <= scopes, role
