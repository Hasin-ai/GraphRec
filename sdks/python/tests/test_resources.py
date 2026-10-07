"""Every route in ``ROUTES`` is exercised through its public SDK method."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx
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
        "auth.refresh",
        "/v1/auth/refresh",
        fx.tokens(),
        lambda c: c.tenant.auth.refresh(refresh_token="r1"),
        body=lambda b: b == {"refresh_token": "r1"},
        check=lambda r: r.access_token == "access-1",
    ),
    Case(
        "health.ready",
        "/readyz",
        {"status": "ready", "version": "1.1.0", "checks": {}},
        lambda c: c.ready(),
        check=lambda r: r["status"] == "ready",
    ),
    Case(
        "meta.get",
        "/v1/meta",
        {"product": "GraphRec", "version": "1.1.0", "environment": "development",
         "features": {"development_placeholders": True}},
        lambda c: c.meta(),
        check=lambda r: r["version"] == "1.1.0",
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
        lambda c: c.tenant.auth.register(name="Shop", admin_email="o@shop.test"),
        body=_eq({"name": "Shop", "admin_email": "o@shop.test"}),
        check=lambda r: r.setup_token == "one-time-token" and r.setup_token_expires_at is not None,
    ),
    Case(
        "auth.login",
        "/v1/auth/login",
        fx.tokens(),
        lambda c: c.tenant.auth.login(email="a@shop.test", password="pw"),
        body=_eq({"email": "a@shop.test", "password": "pw"}),
        check=lambda r: r.user_role == "tenant_administrator",
    ),
    Case(
        "auth.setup_password",
        "/v1/auth/setup-password",
        fx.tokens(),
        lambda c: c.tenant.auth.setup_password(setup_token="one-time-token", password="long-password"),
        body=_eq({"setup_token": "one-time-token", "password": "long-password"}),
    ),
    Case(
        "auth.recover_password", "/v1/auth/recover-password", {"status": "completed"},
        lambda c: c.tenant.auth.recover_password(recovery_token="one-time-token-long", password="long-password"),
        body=_eq({"recovery_token": "one-time-token-long", "password": "long-password"}),
    ),
    Case(
        "api_keys.list",
        "/v1/api-keys",
        {"items": [fx.api_key()]},
        lambda c: c.tenant.api_keys.list(),
        check=lambda r: r[0].is_active,
        client_kwargs=BEARER,
    ),
    Case(
        "tenant_users.list",
        "/v1/tenant/users",
        {"items": [fx.tenant_user()], "total": 1},
        lambda c: c.tenant.users.list(),
        check=lambda r: r.total == 1 and r[0].role == "tenant_developer",
        client_kwargs=BEARER,
    ),
    Case(
        "tenant_users.invite",
        "/v1/tenant/users",
        fx.tenant_user(invited=True),
        lambda c: c.tenant.users.invite("dev@shop.test", role="tenant_developer", display_name="dev"),
        body=_eq({"email": "dev@shop.test", "role": "tenant_developer", "display_name": "dev"}),
        check=lambda r: r.setup_token == "one-time-setup-token",
        client_kwargs=BEARER,
    ),
    Case(
        "api_keys.get",
        f"/v1/api-keys/{fx.UUID_A}",
        fx.api_key(),
        lambda c: c.tenant.api_keys.get(fx.UUID_A),
        client_kwargs=BEARER,
    ),
    Case(
        "api_keys.create",
        "/v1/api-keys",
        fx.api_key(secret=True),
        lambda c: c.tenant.api_keys.create(
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
        lambda c: c.tenant.api_keys.rotate(fx.UUID_A, reason="scheduled", grace_period_seconds=3600),
        body=_eq({"grace_period_seconds": 3600, "reason": "scheduled"}),
        client_kwargs=BEARER,
    ),
    Case(
        "api_keys.revoke",
        f"/v1/api-keys/{fx.UUID_A}",
        fx.api_key(status="revoked", revoked_at=fx.NOW),
        lambda c: c.tenant.api_keys.revoke(fx.UUID_A),
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
        lambda c: c.tenant.subscription.get(),
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
        lambda c: c.tenant.usage.get(),
    ),
    Case(
        "products.bulk_upsert",
        "/v1/products:bulk-upsert",
        fx.bulk_result(created=2),
        lambda c: c.tenant.catalog.bulk_upsert(
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
        "products.list_syncs", "/v1/catalog-syncs",
        [{"sync_id": fx.UUID_A, "status": "completed", "created_at": fx.NOW,
          **fx.bulk_result(created=1)}],
        lambda c: c.tenant.catalog.list_syncs(),
    ),
    Case(
        "products.get_sync", f"/v1/catalog-syncs/{fx.UUID_A}",
        {"sync_id": fx.UUID_A, "status": "completed", "created_at": fx.NOW,
         **fx.bulk_result(created=1)},
        lambda c: c.tenant.catalog.get_sync(fx.UUID_A),
    ),
    Case(
        "products.list",
        "/v1/products",
        {"items": [fx.product()], "total": 1},
        lambda c: c.tenant.catalog.list(),
        check=lambda r: r.total == 1 and r[0].price == Decimal("49.90"),
    ),
    Case("products.get", "/v1/products/sku-1", fx.product(), lambda c: c.tenant.catalog.get("sku-1")),
    Case(
        "products.upsert",
        "/v1/products/sku-1",
        fx.product(),
        lambda c: c.tenant.catalog.upsert(g.ProductInput(external_id="sku-1", title="Linen shirt")),
        body=_has(external_id="sku-1", title="Linen shirt", price="0.00", is_active=True),
    ),
    Case(
        "products.disable",
        "/v1/products/sku-1:disable",
        fx.product(is_active=False),
        lambda c: c.tenant.catalog.disable("sku-1"),
        body=lambda b: b is None,
    ),
    Case(
        "events.create",
        "/v1/events",
        {"event_id": "evt-1", "accepted": True, "duplicate": False, "received_at": fx.NOW},
        lambda c: c.storefront.events.create(
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
        lambda c: c.storefront.events.create_batch(
            [
                {"event_type": "click", "event_id": "e1"},
                g.EventInput(event_type="purchase", event_id="e2"),
            ]
        ),
        body=lambda b: [e["event_id"] for e in b["events"]] == ["e1", "e2"],
        check=lambda r: r.accepted_count == 2 and len(r.batches) == 1,
    ),
    Case(
        "events.list",
        "/v1/events",
        [{"event_id": "e1", "event_type": "view", "user_id": "u1", "external_product_id": "sku-1",
          "context": {}, "occurred_at": "2026-10-07T00:00:00Z", "created_at": "2026-10-07T00:00:01Z"}],
        lambda c: c.storefront.events.list(limit=10, user_id="u1"),
        check=lambda r: len(r) == 1 and r[0].event_id == "e1",
    ),
    Case(
        "events.list_batches",
        "/v1/events/batches",
        [fx.event_batch()],
        lambda c: c.storefront.events.list_batches(),
        check=lambda r: len(r) == 1,
    ),
    Case(
        "events.get_batch",
        f"/v1/events/batches/{fx.UUID_A}",
        fx.event_batch(),
        lambda c: c.storefront.events.get_batch(fx.UUID_A),
    ),
    Case(
        "datasets.upload",
        "/v1/datasets/upload",
        {"accepted_events": 1, "accepted_products": 1, "dataset_snapshot": fx.snapshot()},
        lambda c: c.tenant.datasets.upload(("export.csv", b"external_id,title\nsku-1,Shirt\n")),
        check=lambda r: r.dataset_snapshot.event_count == 10,
    ),
    Case(
        "datasets.create_snapshot",
        "/v1/datasets/snapshots",
        fx.snapshot(),
        lambda c: c.tenant.datasets.create_snapshot(cutoff_at=EXPIRES, description="weekly"),
        body=_eq({"cutoff_at": "2030-01-01T00:00:00+00:00", "description": "weekly"}),
    ),
    Case(
        "datasets.list_snapshots",
        "/v1/datasets/snapshots",
        {"items": [fx.snapshot()]},
        lambda c: c.tenant.datasets.list_snapshots(),
    ),
    Case(
        "datasets.get_snapshot",
        f"/v1/datasets/snapshots/{fx.UUID_A}",
        fx.snapshot(),
        lambda c: c.tenant.datasets.get_snapshot(fx.UUID_A),
    ),
    Case(
        "model_versions.create",
        "/v1/model-versions",
        fx.model_version(),
        lambda c: c.tenant.model_versions.create(version_tag="v1", metrics={"ndcg_at_10": 0.7}),
        body=_eq(
            {"version_tag": "v1", "model_type": "dgsr", "metrics": {"ndcg_at_10": 0.7}}
        ),
    ),
    Case(
        "model_versions.list",
        "/v1/model-versions",
        {"items": [fx.model_version("active"), fx.model_version("retired", fx.UUID_A)]},
        lambda c: c.tenant.model_versions.list(),
        check=lambda r: r.active is not None and str(r.active.id) == fx.UUID_B,
    ),
    Case(
        "model_versions.get",
        f"/v1/model-versions/{fx.UUID_B}",
        fx.model_version(),
        lambda c: c.tenant.model_versions.get(fx.UUID_B),
    ),
    Case(
        "model_versions.activate",
        f"/v1/model-versions/{fx.UUID_B}:activate",
        fx.model_version("active"),
        lambda c: c.tenant.model_versions.activate(fx.UUID_B),
        check=lambda r: r.is_active,
    ),
    Case(
        "model_versions.archive",
        f"/v1/model-versions/{fx.UUID_B}:archive",
        fx.model_version("archived"),
        lambda c: c.tenant.model_versions.archive(fx.UUID_B),
    ),
    Case(
        "model_versions.rollback",
        f"/v1/models/{fx.UUID_B}:rollback",
        fx.model_version("active"),
        lambda c: c.tenant.model_versions.rollback(fx.UUID_B),
    ),
    Case(
        "training_jobs.create",
        "/v1/training-jobs",
        fx.training_job(),
        lambda c: c.tenant.training_jobs.create(
            dataset_snapshot_id=fx.UUID_A, configuration={"epochs": 10}
        ),
        body=_eq(
            {
                "model_type": "dgsr",
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
        lambda c: c.tenant.training_jobs.list(),
    ),
    Case(
        "training_jobs.get",
        f"/v1/training-jobs/{fx.UUID_A}",
        fx.training_job(),
        lambda c: c.tenant.training_jobs.get(fx.UUID_A),
    ),
    Case(
        "training_jobs.cancel",
        f"/v1/training-jobs/{fx.UUID_A}:cancel",
        fx.training_job("cancelled"),
        lambda c: c.tenant.training_jobs.cancel(fx.UUID_A),
    ),
    Case(
        "deployment.get",
        "/v1/deployment",
        {
            "status": "available",
            "active_model_version_id": fx.UUID_B,
            "last_transition_at": fx.NOW,
            "failure_reason": None,
        },
        lambda c: c.tenant.deployment.get(),
    ),
    Case(
        "metrics.summary",
        "/v1/metrics/summary",
        {
            "window_start": fx.NOW,
            "window_end": fx.NOW,
            "request_count": 40,
            "request_rate": 0.667,
            "error_rate": 0.0,
            "fallback_rate": 0.025,
            "p95_latency_ms": 185,
            "active_model_version_id": fx.UUID_B,
            "quality": {
                "model_version_id": fx.UUID_B,
                "version_tag": "v1",
                "recorded_at": fx.NOW,
                "metrics": {"validation": {"NDCG@10": 0.3378}},
            },
        },
        lambda c: c.tenant.metrics.summary(),
        check=lambda r: r.quality is not None
        and r.quality.metrics["validation"]["NDCG@10"] == 0.3378,
    ),
    Case(
        "metrics.summary",
        "/v1/metrics/summary",
        {
            "window_start": fx.NOW,
            "window_end": fx.NOW,
            "request_count": 0,
            "request_rate": 0.0,
            "error_rate": None,
            "fallback_rate": None,
            "p95_latency_ms": None,
            "active_model_version_id": None,
            "quality": None,
        },
        lambda c: c.tenant.metrics.summary(window_minutes=120),
        check=lambda r: r.p95_latency_ms is None and r.error_rate is None,
    ),
    Case(
        "recommendations.get",
        "/v1/recommendations",
        fx.recommendations(),
        lambda c: c.storefront.recommendations.get(
            user_id="u1", top_n=3, exclude_product_ids=["sku-9", "sku-9"],
            request_id="rec-once", fallback_allowed=False,
        ),
        body=_eq({"top_n": 3, "context": {}, "user_id": "u1", "exclude_product_ids": ["sku-9"],
                  "request_id": "rec-once", "fallback_allowed": False}),
        check=lambda r: r.product_ids == ["sku-1", "sku-2", "sku-3"] and r.is_personalized,
    ),
    Case(
        "recommendations.for_session",
        "/v1/recommendations/session",
        fx.recommendations(),
        lambda c: c.storefront.recommendations.for_session(
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
        lambda c: c.storefront.feedback.impression("rec-1", items=["sku-1", "sku-2"], event_id="imp-1"),
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
        lambda c: c.storefront.feedback.click("rec-1", "sku-2", position=2, impression_event_id="imp-1"),
        body=_has(
            request_id="rec-1", external_product_id="sku-2", position=2, impression_event_id="imp-1"
        ),
    ),
    Case(
        "feedback.conversion",
        "/v1/feedback/conversions",
        fx.feedback("conversion"),
        lambda c: c.storefront.feedback.conversion("rec-1", "sku-2", value=49.9),
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
        lambda c: c.platform.tenants.list(),
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.get_tenant",
        f"/v1/platform/tenants/{fx.UUID_A}",
        {"id": fx.UUID_A, "slug": "shop", "name": "Shop", "status": "active", "created_at": fx.NOW},
        lambda c: c.platform.tenants.get(fx.UUID_A),
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.get_tenant_quota",
        f"/v1/platform/tenants/{fx.UUID_A}/quotas",
        {"plan_id": fx.UUID_B, "plan_code": "basic", "limits": {"accepted_events": 100}, "overrides": {}},
        lambda c: c.platform.tenants.get_quota(fx.UUID_A),
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.get_tenant_usage",
        f"/v1/platform/tenants/{fx.UUID_A}/usage",
        {"period_start": fx.NOW, "period_end": "2026-10-01T00:00:00Z", "reset_at": "2026-10-01T00:00:00Z",
         "dimensions": [], "last_reconciled_at": fx.NOW, "project_defaults": False},
        lambda c: c.platform.tenants.get_usage(fx.UUID_A),
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
        lambda c: c.platform.tenants.set_status(fx.UUID_A, g.TenantStatus.SUSPENDED),
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
        lambda c: c.platform.plans.list(),
        check=lambda r: r[0].code == "free",
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.update_plan",
        f"/v1/platform/plans/{fx.UUID_A}",
        {"id": fx.UUID_A, "code": "free", "name": "Free", "limits": {"accepted_events": 100}, "is_active": True},
        lambda c: c.platform.plans.update(fx.UUID_A, name="Free", limits={"accepted_events": 100}, is_active=True),
        body=_eq({"name": "Free", "limits": {"accepted_events": 100}, "is_active": True}),
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.issue_recovery", f"/v1/platform/tenants/{fx.UUID_A}/recovery",
        {"recovery_token": "secret", "expires_at": fx.NOW},
        lambda c: c.platform.tenants.issue_recovery(fx.UUID_A, email="a@shop.test"),
        body=_eq({"email": "a@shop.test"}), client_kwargs=PLATFORM,
    ),
    Case(
        "platform.set_quota_override",
        f"/v1/platform/tenants/{fx.UUID_A}/quotas",
        {"limits": {"accepted_events": 50000}, "overrides": {"accepted_events": 1000000}},
        lambda c: c.platform.tenants.set_quota_override(
            fx.UUID_A, overrides={"accepted_events": 1_000_000}
        ),
        body=_eq({"overrides": {"accepted_events": 1000000}}),
        check=lambda r: r.overrides["accepted_events"] == 1_000_000,
        client_kwargs=PLATFORM,
    ),
    Case(
        "platform.assign_tenant_plan",
        f"/v1/platform/tenants/{fx.UUID_A}/plan",
        {"plan_id": fx.UUID_B, "plan_code": "basic", "limits": {"accepted_events": 100}, "overrides": {}},
        lambda c: c.platform.tenants.assign_plan(fx.UUID_A, fx.UUID_B),
        body=_eq({"plan_id": fx.UUID_B}),
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
        {
            "status": "healthy",
            "api_cluster": "online",
            "database": "connected",
            "worker_pool": "online",
            "deployments": None,
            "rate_limiter": {"backend": "redis", "status": "ok"},
            "timestamp": fx.NOW,
        },
        lambda c: c.platform.status(),
        check=lambda r: r.status == "healthy" and r.rate_limiter["status"] == "ok",
        client_kwargs=PLATFORM,
    ),
    # -- routes added in 2.0 ---------------------------------------------------------
    Case(
        "auth.logout",
        "/v1/auth/logout",
        lambda _req: httpx.Response(204),
        lambda c: c.tenant.auth.logout(),
        check=lambda r: r is None,
        client_kwargs=BEARER,
    ),
    Case(
        "tenant_users.revoke_invitation",
        f"/v1/tenant/users/{fx.UUID_A}/invitation",
        {
            "id": fx.UUID_A,
            "email": "dev@shop.test",
            "display_name": "Dev",
            "role": "tenant_developer",
            "status": "disabled",
            "created_at": fx.NOW,
        },
        lambda c: c.tenant.users.revoke_invitation(fx.UUID_A),
        check=lambda r: r.status == "disabled",
        client_kwargs=BEARER,
    ),
    Case(
        "usage.trends",
        "/v1/usage/trends",
        {
            "tenant_id": fx.UUID_A,
            "start": "2026-09-01T00:00:00Z",
            "end": "2026-09-03T00:00:00Z",
            "granularity": "day",
            "usage_types": ["accepted_events"],
            "buckets": [{"start": "2026-09-01T00:00:00Z", "values": {"accepted_events": 3}}],
            "totals": {"accepted_events": 3},
        },
        lambda c: c.tenant.usage.trends(types=[g.UsageType.ACCEPTED_EVENTS]),
        check=lambda r: r.totals["accepted_events"] == 3 and r.buckets[0].values["accepted_events"] == 3,
    ),
    Case(
        "deployment.scaling",
        "/v1/deployment/scaling",
        {
            "managed": True,
            "desired_capacity": 2,
            "ready_capacity": 2,
            "min_capacity": 1,
            "max_capacity": 4,
            "serving_slots": 16,
            "target_rpm_per_replica": 120,
            "scale_down_stabilization_seconds": 300,
            "measured_rpm": 80,
            "peak_rpm": 200,
            "last_scaled_at": fx.NOW,
            "events": [
                {
                    "id": fx.UUID_B,
                    "model_version_id": None,
                    "from_capacity": 1,
                    "to_capacity": 2,
                    "reason": "demand",
                    "measured_rpm": 200,
                    "peak_rpm": 200,
                    "max_capacity": 4,
                    "occurred_at": fx.NOW,
                }
            ],
            "limitation": "simulated",
        },
        lambda c: c.tenant.deployment.scaling(limit=5),
        check=lambda r: r.events[0].to_capacity == 2 and r.serving_slots == 16,
    ),
    Case(
        "recommendation_policy.get",
        "/v1/recommendation-policy",
        {
            "tenant_id": fx.UUID_A,
            "configured": False,
            "version": 0,
            "diversity_enabled": False,
            "max_per_category": 3,
            "freshness_enabled": False,
            "freshness_weight": 0.2,
            "freshness_half_life_days": 30,
        },
        lambda c: c.tenant.recommendation_policy.get(),
        check=lambda r: r.max_per_category == 3 and not r.configured,
    ),
    Case(
        "recommendation_policy.update",
        "/v1/recommendation-policy",
        {
            "tenant_id": fx.UUID_A,
            "configured": True,
            "version": 1,
            "diversity_enabled": True,
            "max_per_category": 2,
            "freshness_enabled": False,
            "freshness_weight": 0.2,
            "freshness_half_life_days": 30,
            "updated_at": fx.NOW,
        },
        lambda c: c.tenant.recommendation_policy.update(diversity_enabled=True, max_per_category=2),
        body=_eq(
            {
                "diversity_enabled": True,
                "max_per_category": 2,
                "freshness_enabled": False,
                "freshness_weight": 0.2,
                "freshness_half_life_days": 30,
            }
        ),
        check=lambda r: r.version == 1,
    ),
    Case(
        "retraining_policy.get",
        "/v1/retraining-policy",
        {
            "tenant_id": fx.UUID_A,
            "configured": False,
            "schedule_enabled": False,
            "interval_minutes": 1440,
            "event_trigger_enabled": False,
            "event_threshold": 1000,
            "epochs": 3,
            "new_events_since_last_training": 12,
            "training_in_progress": False,
            "minimum_interval_minutes": 60,
        },
        lambda c: c.tenant.retraining_policy.get(),
        check=lambda r: r.new_events_since_last_training == 12,
    ),
    Case(
        "retraining_policy.update",
        "/v1/retraining-policy",
        {
            "tenant_id": fx.UUID_A,
            "configured": True,
            "schedule_enabled": True,
            "interval_minutes": 720,
            "event_trigger_enabled": False,
            "event_threshold": 1000,
            "epochs": 3,
            "new_events_since_last_training": 0,
            "training_in_progress": False,
            "minimum_interval_minutes": 60,
        },
        lambda c: c.tenant.retraining_policy.update(schedule_enabled=True, interval_minutes=720),
        body=_has(schedule_enabled=True, interval_minutes=720, epochs=3),
        check=lambda r: r.configured,
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
        updated = client.tenant.catalog.update(
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
        client.tenant.datasets.upload(export)
    assert b'filename="catalog.json"' in api.last().request.content
    assert b"Content-Type: application/json" in api.last().request.content


def test_training_job_wait_polls_until_terminal(
    api: MockAPI, sleeps: List[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    api.queue(
        "GET",
        f"/v1/training-jobs/{fx.UUID_A}",
        fx.training_job("training"),
        fx.training_job("succeeded"),
    )
    monkeypatch.setattr("graphrec_sdk.resources.ml.time.sleep", lambda _s: None)
    with make_client(api, sleeps) as client:
        job = client.tenant.training_jobs.wait(fx.UUID_A, poll_interval=0.01, timeout=5)
    assert job.succeeded and len(api.calls) == 2


def test_training_job_wait_times_out(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", f"/v1/training-jobs/{fx.UUID_A}", fx.training_job("training"))
    with make_client(api, sleeps) as client, pytest.raises(g.WaitTimeoutError):
        client.tenant.training_jobs.wait(fx.UUID_A, poll_interval=0.01, timeout=0.02)


def test_training_job_find_returns_none_for_unknown_job(api: MockAPI, sleeps: List[float]) -> None:
    with make_client(api, sleeps) as client:
        assert client.tenant.training_jobs.find(fx.UUID_B) is None
    assert api.paths() == [f"GET /v1/training-jobs/{fx.UUID_B}"]


def test_get_active_version_returns_none_without_active(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", "/v1/model-versions", {"items": [fx.model_version("eligible")]})
    with make_client(api, sleeps) as client:
        assert client.tenant.model_versions.get_active() is None


def test_feedback_from_recommendations_object(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/recommendations", fx.recommendations())
    api.on("POST", "/v1/feedback/impressions", fx.feedback("impression", "imp-9"))
    api.on("POST", "/v1/feedback/clicks", fx.feedback("click"))
    with make_client(api, sleeps) as client:
        recs = client.storefront.recommendations.get(user_id="u1")
        client.storefront.feedback.impression(recs)
        assert api.last().json()["items"][2] == {"external_product_id": "sku-3", "position": 3}
        client.storefront.feedback.click(recs, "sku-3")
        assert api.last().json()["position"] == 3
        with pytest.raises(g.InputValidationError):
            client.storefront.feedback.click(recs, "sku-404")
        with pytest.raises(g.InputValidationError):
            client.storefront.feedback.click("rec-1", "sku-1")
        with pytest.raises(g.InputValidationError):
            client.storefront.feedback.impression("rec-1")


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.storefront.recommendations.get(top_n=0),
        lambda c: c.storefront.recommendations.get(top_n=101),
        lambda c: c.storefront.recommendations.get(exclude_product_ids=[str(i) for i in range(201)]),
        lambda c: c.tenant.catalog.upsert({"external_id": "", "title": "x"}),
        lambda c: c.tenant.catalog.upsert({"external_id": "a", "title": "x", "price": -1}),
        lambda c: c.tenant.catalog.upsert({"external_id": "a", "title": "x", "colour": "red"}),
        lambda c: c.storefront.events.create("x" * 49),
        lambda c: c.storefront.feedback.conversion("rec-1", "sku-1", value=-5),
        lambda c: c.tenant.model_versions.create(version_tag=""),
        lambda c: c.storefront.recommendations.for_session(""),
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
            client.tenant.api_keys.create(name="k", scopes=[])
        with pytest.raises(g.InputValidationError):
            client.tenant.api_keys.create(name="k", scopes=["catalog:read", g.Scope.CATALOG_READ])
        with pytest.raises(g.InputValidationError):
            client.tenant.api_keys.create(
                name="k", scopes=["catalog:read"], expires_at=datetime(2030, 1, 1)
            )
        with pytest.raises(g.InputValidationError):
            client.tenant.api_keys.rotate(fx.UUID_A, reason="x", grace_period_seconds=90_000)
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
        client.tenant.auth.setup_password(setup_token="tok", password="long-password", email="a@shop.test")
        assert api.last().json() == {
            "setup_token": "tok",
            "password": "long-password",
            "email": "a@shop.test",
        }
        with pytest.raises(g.AuthenticationError) as caught:
            client.tenant.auth.setup_password(setup_token="tok", password="long-password")
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
        tenant = client.tenant.auth.register(name="Shop", admin_email="o@shop.test")
    assert tenant.setup_token is None and tenant.setup_token_expires_at is None


def test_required_scopes() -> None:
    assert g.ROUTES["datasets.upload"].required_scopes == ("catalog:write", "events:write")
    assert g.ROUTES["products.list"].required_scopes == ("catalog:read",)
    assert g.ROUTES["health.check"].required_scopes == ()
    tenant_routes = [
        route
        for route in g.ROUTES.values()
        if route.auth != "none"
        and not route.key.startswith("platform.")
        # Logout only needs a signed-in user, whatever their scopes.
        and route.key != "auth.logout"
    ]
    assert tenant_routes and all(route.scope_enforced for route in tenant_routes)
    # A role delegates API-key-compatible scopes only. It need not hold every
    # scope it delegates: a developer grants a storefront key
    # recommendations:read without serving recommendations from the console.
    for role in g.ROLE_SCOPES:
        assert g.DELEGATABLE_SCOPES[role] <= g.API_KEY_SCOPES, role
    assert "recommendations:read" in g.DELEGATABLE_SCOPES["tenant_developer"]
    assert not g.DELEGATABLE_SCOPES["tenant_developer"] & {"training:write", "models:deploy"}


# -- 2.0 behaviour ----------------------------------------------------------------------


def test_usage_trends_query(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", "/v1/usage/trends", {"tenant_id": "t", "start": fx.NOW, "end": fx.NOW,
                                       "granularity": "week", "usage_types": [], "buckets": [], "totals": {}})
    with make_client(api, sleeps) as client:
        client.tenant.usage.trends(
            granularity="week",
            start=datetime(2026, 9, 1),
            end=datetime(2026, 9, 8, tzinfo=timezone.utc),
            types=["accepted_events", g.UsageType.RECOMMENDATION_REQUESTS],
        )
        params = api.last().request.url.params
        assert params["granularity"] == "week"
        assert params["start"] == "2026-09-01T00:00:00+00:00"  # naive -> UTC
        assert params["end"] == "2026-09-08T00:00:00+00:00"
        assert params["types"] == "accepted_events,recommendation_requests"
        client.tenant.usage.trends()
        assert set(api.last().request.url.params) == {"granularity"}
        with pytest.raises(g.InputValidationError):
            client.tenant.usage.trends(granularity="month")
        with pytest.raises(g.InputValidationError):
            client.tenant.usage.trends(start=datetime(2026, 9, 2), end=datetime(2026, 9, 1))


def test_scaling_limit_is_validated(api: MockAPI, sleeps: List[float]) -> None:
    with make_client(api, sleeps) as client:
        for bad in (0, 101, True):
            with pytest.raises(g.InputValidationError):
                client.tenant.deployment.scaling(limit=bad)
    assert api.calls == []


def test_policy_update_accepts_current_policy_and_validates(api: MockAPI, sleeps: List[float]) -> None:
    current = g.models.RecommendationPolicy(
        tenant_id=fx.UUID_A, configured=True, version=3, diversity_enabled=True, max_per_category=4,
        freshness_enabled=True, freshness_weight=0.1, freshness_half_life_days=10,
    )
    api.on("PUT", "/v1/recommendation-policy", lambda req: {**current.model_dump(mode="json"), "version": 4})
    with make_client(api, sleeps) as client:
        client.tenant.recommendation_policy.update(current, max_per_category=2)
        assert api.last().json() == {
            "diversity_enabled": True, "max_per_category": 2, "freshness_enabled": True,
            "freshness_weight": 0.1, "freshness_half_life_days": 10,
        }
        with pytest.raises(g.InputValidationError):
            client.tenant.recommendation_policy.update(freshness_weight=0.9)
        with pytest.raises(g.InputValidationError):
            client.tenant.recommendation_policy.update({"diversity": True})  # typo
        with pytest.raises(g.InputValidationError):
            client.tenant.retraining_policy.update(epochs=11)
    assert len(api.calls) == 1


def test_limit_changes_send_acknowledgement(api: MockAPI, sleeps: List[float]) -> None:
    quota = {"plan_id": fx.UUID_B, "plan_code": "basic", "limits": {"stored_products": 1}, "overrides": {},
             "warnings": [{"limit_name": "stored_products", "limit": 1, "used": 5, "over_by": 4}]}
    api.on("POST", f"/v1/platform/tenants/{fx.UUID_A}/plan", quota)
    api.on("POST", f"/v1/platform/tenants/{fx.UUID_A}/quotas", quota)
    api.on("PUT", f"/v1/platform/plans/{fx.UUID_B}", {"id": fx.UUID_B, "code": "basic", "name": "Basic",
                                                     "limits": {"stored_products": 1}, "is_active": True,
                                                     "warnings": [{"limit_name": "stored_products", "limit": 1,
                                                                   "used": 5, "over_by": 4,
                                                                   "tenant_id": fx.UUID_A, "tenant_name": "Shop"}]})
    with make_client(api, sleeps, **PLATFORM) as client:
        result = client.platform.tenants.assign_plan(fx.UUID_A, fx.UUID_B, acknowledge_below_usage=True)
        assert api.last().json() == {"plan_id": fx.UUID_B, "acknowledge_below_usage": True}
        assert result.warnings[0].over_by == 4
        client.platform.tenants.set_quota_override(
            fx.UUID_A, overrides={"stored_products": 1}, acknowledge_below_usage=True
        )
        assert api.last().json()["acknowledge_below_usage"] is True
        plan = client.platform.plans.update(
            fx.UUID_B, name="Basic", limits={"stored_products": 1}, is_active=True, acknowledge_below_usage=True
        )
        assert api.last().json()["acknowledge_below_usage"] is True
        assert plan.warnings[0].tenant_name == "Shop"
        with pytest.raises(g.InputValidationError):
            client.platform.tenants.set_quota_override(fx.UUID_A, overrides={"stored_products": -1})


def test_limit_below_usage_error(api: MockAPI, sleeps: List[float]) -> None:
    conflict = {"limit_name": "stored_products", "limit": 1, "used": 5, "over_by": 4}
    api.on("POST", f"/v1/platform/tenants/{fx.UUID_A}/plan",
           fx.error(409, "limit_below_usage", details={"conflicts": [conflict]}))
    with make_client(api, sleeps, **PLATFORM) as client:
        with pytest.raises(g.LimitBelowUsageError) as info:
            client.platform.tenants.assign_plan(fx.UUID_A, fx.UUID_B)
    assert isinstance(info.value, g.ConflictError)
    assert info.value.conflicts == [conflict]
    assert sleeps == []  # a refused change is not retried


def test_logout_forgets_password_session(api: MockAPI, sleeps: List[float]) -> None:
    logins: List[int] = []

    def login(_req: httpx.Request) -> Dict[str, Any]:
        logins.append(1)
        return {"access_token": f"jwt-{len(logins)}", "refresh_token": "r", "token_type": "bearer",
                "expires_in": 900, "user_role": "tenant_administrator",
                "scopes": ["users:write"]}

    api.on("POST", "/v1/auth/login", login)
    api.on("POST", "/v1/auth/logout", lambda _r: httpx.Response(204))
    api.on("GET", "/v1/tenant/users", {"items": [], "total": 0})
    with make_client(api, sleeps, api_key=None, email="a@shop.test", password="secret-pass") as client:
        client.tenant.users.list()
        client.tenant.auth.logout()
        client.tenant.users.list()
    assert len(logins) == 2
    assert api.last().headers["Authorization"] == "Bearer jwt-2"


def test_logout_requires_a_bearer_credential(api: MockAPI, sleeps: List[float]) -> None:
    with make_client(api, sleeps) as client:
        with pytest.raises(g.ConfigurationError):
            client.tenant.auth.logout()
    assert api.calls == []


def test_event_batch_outcomes_accept_null_reason(api: MockAPI, sleeps: List[float]) -> None:
    # The server sends ``reason: null`` for accepted events (regression: 0.2.0 rejected it).
    batch = {**fx.event_batch(accepted=1), "outcomes": [{"event_id": "e1", "status": "accepted", "reason": None}]}
    api.on("GET", f"/v1/events/batches/{fx.UUID_A}", batch)
    with make_client(api, sleeps) as client:
        result = client.storefront.events.get_batch(fx.UUID_A)
    assert result.outcomes[0].status == "accepted" and result.outcomes[0].reason is None
