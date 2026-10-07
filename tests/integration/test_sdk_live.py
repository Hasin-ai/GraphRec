"""The Python SDK against the real FastAPI app and PostgreSQL.

Every SDK method is exercised at least once through ``fastapi.testclient``
(an ``httpx.Client``), so request encoding, auth headers, response models and
error mapping are checked against the live routes, not mocks. Requires the
Compose PostgreSQL database (and Qdrant for model activation), like the other
integration tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

import graphrec_sdk as g
from apps.api.main import app
from graphrec_core.settings import get_settings

pytestmark = pytest.mark.integration

BASE_URL = "http://testserver"
PASSWORD = "sdk-integration-password"
ROOMY = {"training_jobs": 50, "stored_products": 1000, "active_model_versions": 10}


@dataclass
class Tenant:
    id: UUID
    email: str
    admin: g.GraphRec
    store: g.GraphRec
    store_key_id: UUID


def _public(http: TestClient) -> g.GraphRec:
    return g.GraphRec(base_url=BASE_URL, http_client=http, use_env=False, max_retries=0)


def _provision(public: g.GraphRec, label: str) -> Tenant:
    suffix = uuid4().hex[:10]
    email = f"sdk-{label}-{suffix}@example.org"
    registration = public.tenant.auth.register(name=f"SDK {label} {suffix}", admin_email=email)
    assert registration.setup_token
    public.tenant.auth.setup_password(setup_token=registration.setup_token, password=PASSWORD, email=email)
    admin = public.with_credentials(email=email, password=PASSWORD)
    key = admin.tenant.api_keys.create(name=f"store-{suffix}", scopes=g.STOREFRONT_KEY_SCOPES)
    return Tenant(registration.id, email, admin, public.with_credentials(api_key=key.secret), key.id)


#: Route keys that returned a 2xx response through the SDK during this module.
SUCCEEDED: set[str] = set()


@pytest.fixture(scope="module", autouse=True)
def _record_routes() -> Iterator[None]:
    sync_request = g._base_client.SyncAPIClient.request
    async_request = g._base_client.AsyncAPIClient.request

    def record(self, route_key, **kwargs):  # type: ignore[no-untyped-def]
        result = sync_request(self, route_key, **kwargs)
        SUCCEEDED.add(route_key)
        return result

    async def arecord(self, route_key, **kwargs):  # type: ignore[no-untyped-def]
        result = await async_request(self, route_key, **kwargs)
        SUCCEEDED.add(route_key)
        return result

    g._base_client.SyncAPIClient.request = record  # type: ignore[method-assign]
    g._base_client.AsyncAPIClient.request = arecord  # type: ignore[method-assign]
    yield
    g._base_client.SyncAPIClient.request = sync_request  # type: ignore[method-assign]
    g._base_client.AsyncAPIClient.request = async_request  # type: ignore[method-assign]


@pytest.fixture(scope="module")
def http() -> Iterator[TestClient]:
    with TestClient(app, base_url=BASE_URL) as client:
        yield client


@pytest.fixture(autouse=True)
def _fresh_rate_limits() -> None:
    from apps.api.routes.api_keys import api_key_limiter
    from apps.api.routes.auth import login_limiter, setup_limiter
    from apps.api.routes.subscriptions import subscription_limiter
    from apps.api.routes.tenants import registration_limiter
    from apps.api.routes.usage import usage_limiter

    for limiter in (registration_limiter, login_limiter, setup_limiter, api_key_limiter,
                    subscription_limiter, usage_limiter):
        limiter.clear()


@pytest.fixture(scope="module")
def public(http: TestClient) -> g.GraphRec:
    return _public(http)


@pytest.fixture(scope="module")
def shop(public: g.GraphRec, ops: g.GraphRec) -> Tenant:
    tenant = _provision(public, "a")
    # Free-plan limits are too small for the full walk-through.
    ops.platform.tenants.set_quota_override(tenant.id, overrides=ROOMY)
    return tenant


@pytest.fixture(scope="module")
def other(public: g.GraphRec) -> Tenant:
    return _provision(public, "b")


@pytest.fixture(scope="module")
def ops(public: g.GraphRec) -> g.GraphRec:
    token = get_settings().platform_admin_token
    if not token:
        pytest.skip("PLATFORM_ADMIN_TOKEN is not configured")
    return public.with_credentials(access_token=token)


# -- storefront ---------------------------------------------------------------------


def test_health(public: g.GraphRec) -> None:
    assert public.health()["status"] in {"ok", "healthy"}


def test_catalog_lifecycle(shop: Tenant) -> None:
    catalog = shop.admin.tenant.catalog
    result = catalog.bulk_upsert(
        [{"external_id": f"sku-{i}", "title": f"Item {i}", "price": "10.00", "category": ["a", "b"][i % 2]}
         for i in range(12)],
        request_id=f"sync-{uuid4().hex[:8]}",
    )
    assert result.created_count == 12 and result.rejected_count == 0
    syncs = catalog.list_syncs()
    assert syncs and catalog.get_sync(syncs[0].sync_id).sync_id == syncs[0].sync_id
    page = catalog.list(limit=5)
    assert page.total == 12 and len(page) == 5
    assert {p.external_id for p in catalog.list(external_ids=["sku-1", "sku-2"])} == {"sku-1", "sku-2"}
    assert sum(1 for _ in catalog.iterate(page_size=5)) == 12
    assert catalog.get("sku-1").title == "Item 1"
    catalog.upsert({"external_id": "sku-new", "title": "New"})
    updated = catalog.update("sku-1", price="9.50", metadata={"brand": "Acme"})
    assert str(updated.price) == "9.50" and updated.metadata["brand"] == "Acme"
    assert updated.category == "b"  # update keeps fields it was not given
    assert catalog.disable("sku-11").is_active is False
    with pytest.raises(g.NotFoundError):
        catalog.get("does-not-exist")
    with pytest.raises(g.NotFoundError):
        catalog.update("does-not-exist", title="x")


def test_events_and_batches(shop: Tenant) -> None:
    events = shop.store.storefront.events
    first = events.create("view", user_id="u-1", product_id="sku-1", event_id=f"evt-{uuid4().hex}")
    assert first.accepted and not first.duplicate
    again = events.create("view", user_id="u-1", product_id="sku-1", event_id=first.event_id)
    assert again.duplicate
    batch = events.create_batch(
        [g.EventInput(event_type="purchase", user_id=f"u-{i % 4}", external_product_id=f"sku-{i % 10}")
         for i in range(20)]
    )
    assert batch.accepted_count == 20
    recent = events.list(limit=5, user_id="u-1")
    assert recent and all(item.user_id == "u-1" for item in recent)
    listed = events.list_batches()
    assert listed and events.get_batch(listed[0].id).id == listed[0].id
    with pytest.raises(g.RequestValidationError):
        events.create_batch([{"event_type": "not-a-type", "user_id": "u"}])


def test_recommendations_and_feedback(shop: Tenant) -> None:
    store = shop.store.storefront
    recs = store.recommendations.get(user_id="u-1", top_n=4, exclude_product_ids=["sku-0"])
    assert "sku-0" not in recs.product_ids and len(recs) <= 4
    assert isinstance(recs.applied_rules, list)
    session = store.recommendations.for_session("sess-1", recent_product_ids=["sku-3"], top_n=3)
    assert session.request_id
    assert recs.items, "the catalog fallback should return items"
    product = recs.items[0].external_product_id
    impression = store.feedback.impression(recs)
    assert impression.feedback_type == "impression" and impression.accepted
    click = store.feedback.click(recs, product)
    assert click.feedback_type == "click"
    conversion = store.feedback.conversion(recs, product, value="19.90")
    assert conversion.feedback_type == "conversion"
    with pytest.raises(g.NotFoundError):
        store.feedback.click(str(uuid4()), product, position=1)


# -- tenant administration ------------------------------------------------------------


def test_auth_login_logout_and_recovery(public: g.GraphRec, shop: Tenant, ops: g.GraphRec) -> None:
    tokens = public.tenant.auth.login(email=shop.email, password=PASSWORD)
    session = public.with_credentials(access_token=tokens.access_token)
    assert session.tenant.subscription.get().plan_code
    session.tenant.auth.logout()
    with pytest.raises(g.AuthenticationError):
        session.tenant.subscription.get()
    with pytest.raises(g.AuthenticationError):
        public.tenant.auth.login(email=shop.email, password="wrong-password")
    with pytest.raises(g.AuthenticationError):
        public.tenant.auth.setup_password(setup_token="x" * 43, password=PASSWORD)

    recovery = ops.platform.tenants.issue_recovery(shop.id, email=shop.email)
    assert recovery.expires_at > datetime.now(timezone.utc)
    assert public.tenant.auth.recover_password(
        recovery_token=recovery.recovery_token, password=PASSWORD, email=shop.email
    ) == {"status": "completed"}
    with pytest.raises(g.AuthenticationError):
        public.tenant.auth.recover_password(recovery_token=recovery.recovery_token, password=PASSWORD)
    # The PasswordAuth client signs in again on its own after the sessions were reset.
    assert shop.admin.tenant.subscription.get().plan_code


def test_password_client_logout_signs_in_again(shop: Tenant) -> None:
    shop.admin.tenant.users.list()
    shop.admin.tenant.auth.logout()
    assert shop.admin.tenant.users.list().total >= 1


def test_tenant_users(shop: Tenant) -> None:
    users = shop.admin.tenant.users
    invite = users.invite(f"dev-{uuid4().hex[:8]}@example.org", display_name="Dev")
    assert invite.setup_token and invite.status == "invited"
    assert any(u.id == invite.id for u in users.list())
    revoked = users.revoke_invitation(invite.id)
    assert revoked.id == invite.id and revoked.status != "invited"
    with pytest.raises(g.ConflictError):
        users.revoke_invitation(invite.id)
    with pytest.raises(g.NotFoundError):
        users.revoke_invitation(uuid4())
    with pytest.raises(g.ConfigurationError):
        shop.store.tenant.users.list()  # API keys are refused client-side for bearer-only routes


def test_api_keys(shop: Tenant) -> None:
    keys = shop.admin.tenant.api_keys
    created = keys.create(name=f"tmp-{uuid4().hex[:8]}", scopes=["catalog:read"])
    assert keys.get(created.id).name == created.name
    rotated = keys.rotate(created.id, reason="integration", grace_period_seconds=0)
    assert rotated.secret != created.secret
    assert any(k.id == rotated.id for k in keys.list())
    assert keys.revoke(rotated.id).status == "revoked"
    with pytest.raises(g.RequestValidationError):
        keys.create(name="unknown-scope", scopes=["platform:admin"])


def test_billing_and_usage(shop: Tenant) -> None:
    tenant = shop.admin.tenant
    assert tenant.subscription.get().limits
    usage = tenant.usage.get()
    assert any(d.type == "stored_products" for d in usage.dimensions)
    end = datetime.now(timezone.utc) + timedelta(hours=1)
    trend = tenant.usage.trends(granularity="hour", start=end - timedelta(days=1), end=end,
                                types=[g.UsageType.ACCEPTED_EVENTS])
    assert trend.granularity == "hour" and trend.usage_types == ["accepted_events"]
    assert trend.totals.get("accepted_events", 0) >= 0
    assert tenant.usage.trends().granularity == "day"
    with pytest.raises(g.RequestValidationError):
        tenant.usage.trends(types=["no_such_type"])


def test_datasets_training_and_model_registry(shop: Tenant) -> None:
    tenant = shop.admin.tenant
    csv = "event_id,event_type,user_id,external_product_id\n" + "".join(
        f"ds-{uuid4().hex[:6]}-{i},click,u-{i % 5},sku-{i % 10}\n" for i in range(30)
    )
    upload = tenant.datasets.upload(("events.csv", csv.encode()))
    assert upload.accepted_events == 30
    snapshot = tenant.datasets.create_snapshot(description="sdk integration")
    assert tenant.datasets.get_snapshot(snapshot.id).id == snapshot.id
    assert any(s.id == snapshot.id for s in tenant.datasets.list_snapshots())

    job = tenant.training_jobs.create(dataset_snapshot_id=snapshot.id, configuration={"mode": "placeholder"})
    assert tenant.training_jobs.get(job.id).id == job.id
    assert tenant.training_jobs.find(job.id) is not None
    assert any(j.id == job.id for j in tenant.training_jobs.list())
    assert job.model_version_id is not None
    first = tenant.model_versions.activate(job.model_version_id)
    assert first.status == "active" and tenant.model_versions.get_active().id == first.id

    second_job = tenant.training_jobs.create(configuration={"mode": "placeholder"})
    second = tenant.model_versions.activate(second_job.model_version_id)
    assert tenant.deployment.get().active_model_version_id == second.id
    with pytest.raises(g.ConflictError):
        tenant.model_versions.archive(first.id)  # protected rollback target
    assert tenant.model_versions.rollback(first.id).id == first.id
    with pytest.raises(g.ConflictError):
        tenant.model_versions.archive(second.id)  # now the rollback target

    registered = tenant.model_versions.create(
        version_tag=f"ext-{uuid4().hex[:6]}", model_type="simplified_dgsr", metrics={"recall@10": 0.1}
    )
    assert tenant.model_versions.get(registered.id).version_tag == registered.version_tag
    assert any(v.id == registered.id for v in tenant.model_versions.list())
    assert tenant.model_versions.archive(registered.id).status == "archived"

    pending = tenant.training_jobs.create(configuration={})
    if pending.status in {"queued", "running"}:
        assert tenant.training_jobs.cancel(pending.id).status in {"cancelled", "canceled"}


def test_serving_status_and_scaling(shop: Tenant) -> None:
    tenant = shop.admin.tenant
    assert tenant.deployment.get().status
    scaling = tenant.deployment.scaling(limit=5)
    assert scaling.max_capacity >= scaling.min_capacity and len(scaling.events) <= 5
    summary = tenant.metrics.summary(window_minutes=60)
    assert summary.window_end > summary.window_start
    with pytest.raises(g.RequestValidationError):
        tenant.metrics.summary(window_minutes=1)


def test_recommendation_policy(shop: Tenant) -> None:
    policy = shop.admin.tenant.recommendation_policy
    current = policy.get()
    updated = policy.update(current, diversity_enabled=True, max_per_category=2)
    assert updated.diversity_enabled and updated.max_per_category == 2
    assert updated.version > current.version and updated.configured
    recs = shop.store.storefront.recommendations.get(user_id="u-2", top_n=6)
    assert recs.rules_version == updated.version
    with pytest.raises(g.PermissionDeniedError):
        shop.store.tenant.recommendation_policy.get()  # storefront keys have no models:read


def test_retraining_policy(shop: Tenant) -> None:
    policy = shop.admin.tenant.retraining_policy
    current = policy.get()
    interval = max(current.minimum_interval_minutes, 120)
    updated = policy.update(schedule_enabled=True, interval_minutes=interval, epochs=2)
    assert updated.schedule_enabled and updated.interval_minutes == interval and updated.epochs == 2
    assert updated.next_run_at is not None
    if current.minimum_interval_minutes > 1:
        with pytest.raises(g.RequestValidationError):
            policy.update(schedule_enabled=True, interval_minutes=1)
    assert policy.update().schedule_enabled is False


# -- platform administration ---------------------------------------------------------


def test_platform_tenants_quotas_and_plans(ops: g.GraphRec, shop: Tenant) -> None:
    platform = ops.platform
    assert any(t.id == shop.id for t in platform.tenants.list())
    assert platform.tenants.get(shop.id).status == "active"
    with pytest.raises(g.NotFoundError):
        platform.tenants.get(uuid4())

    quota = platform.tenants.get_quota(shop.id)
    usage = platform.tenants.get_usage(shop.id)
    stored = next(d for d in usage.dimensions if d.type == "stored_products")
    assert stored.used >= 12

    # Lowering an inventory limit below what is stored is refused without acknowledgement.
    with pytest.raises(g.LimitBelowUsageError) as refused:
        platform.tenants.set_quota_override(shop.id, overrides={"stored_products": 1})
    assert refused.value.conflicts[0]["limit_name"] == "stored_products"
    assert platform.tenants.get_quota(shop.id).overrides == quota.overrides  # nothing changed
    applied = platform.tenants.set_quota_override(
        shop.id, overrides={"stored_products": 1}, acknowledge_below_usage=True
    )
    assert applied.warnings and applied.warnings[0].limit_name == "stored_products"
    restored = platform.tenants.set_quota_override(shop.id, overrides=ROOMY)
    assert restored.overrides == ROOMY and restored.warnings == []

    plans = platform.plans.list()
    pro = next(p for p in plans if p.code == "pro")
    moved = platform.tenants.assign_plan(shop.id, pro.id)
    assert moved.plan_code == "pro"
    updated = platform.plans.update(pro.id, name=pro.name, limits=dict(pro.limits), is_active=pro.is_active)
    assert updated.id == pro.id and updated.warnings == []
    with pytest.raises(g.RequestValidationError):
        platform.plans.update(pro.id, name=pro.name, limits={"stored_products": 1}, is_active=True)


def test_platform_status_and_monitoring(ops: g.GraphRec, shop: Tenant) -> None:
    status = ops.platform.status()
    assert status.database == "connected" and status.status in {"healthy", "degraded"}
    assert any(a.tenant_id == shop.id for a in ops.platform.list_audit_logs())
    assert isinstance(ops.platform.list_failures().items, list)


def test_platform_suspension_blocks_tenant_credentials(public: g.GraphRec, ops: g.GraphRec) -> None:
    tenant = _provision(public, "suspend")
    assert tenant.store.tenant.catalog.list(limit=1).total == 0
    assert ops.platform.tenants.set_status(tenant.id, g.TenantStatus.SUSPENDED).status == "suspended"
    with pytest.raises((g.AuthenticationError, g.PermissionDeniedError)):
        tenant.store.tenant.catalog.list(limit=1)
    assert ops.platform.tenants.set_status(tenant.id, "active").status == "active"
    assert tenant.store.tenant.catalog.list(limit=1).total == 0
    with pytest.raises(g.RequestValidationError):
        ops.platform.tenants.set_status(tenant.id, "frozen")


# -- authorization and tenant isolation ------------------------------------------------


def test_platform_routes_reject_tenant_credentials(shop: Tenant) -> None:
    with pytest.raises((g.AuthenticationError, g.PermissionDeniedError)):
        shop.admin.platform.tenants.list()
    with pytest.raises((g.AuthenticationError, g.PermissionDeniedError)):
        shop.admin.platform.tenants.get_quota(shop.id)


def test_platform_token_is_not_a_tenant_credential(ops: g.GraphRec) -> None:
    with pytest.raises((g.AuthenticationError, g.PermissionDeniedError)):
        ops.tenant.catalog.list(limit=1)


def test_tenant_isolation(shop: Tenant, other: Tenant) -> None:
    # Ensure tenant A has data and B starts empty.
    shop.admin.tenant.catalog.upsert({"external_id": "iso-1", "title": "Isolated"})
    assert other.store.tenant.catalog.list().total == 0
    with pytest.raises(g.NotFoundError):
        other.store.tenant.catalog.get("iso-1")
    with pytest.raises(g.NotFoundError):
        other.admin.tenant.api_keys.get(shop.store_key_id)
    with pytest.raises(g.NotFoundError):
        other.admin.tenant.api_keys.revoke(shop.store_key_id)
    version = shop.admin.tenant.model_versions.list()
    if version.items:
        with pytest.raises(g.NotFoundError):
            other.admin.tenant.model_versions.activate(version.items[0].id)
        with pytest.raises(g.NotFoundError):
            other.admin.tenant.model_versions.rollback(version.items[0].id)
    batches = shop.store.storefront.events.list_batches()
    if batches:
        with pytest.raises(g.NotFoundError):
            other.store.storefront.events.get_batch(batches[0].id)
    snapshots = shop.admin.tenant.datasets.list_snapshots()
    if snapshots.items:
        with pytest.raises(g.NotFoundError):
            other.admin.tenant.datasets.get_snapshot(snapshots.items[0].id)
    syncs = shop.admin.tenant.catalog.list_syncs()
    if syncs:
        with pytest.raises(g.NotFoundError):
            other.admin.tenant.catalog.get_sync(syncs[0].sync_id)
    invite = shop.admin.tenant.users.invite(f"iso-{uuid4().hex[:8]}@example.org")
    with pytest.raises(g.NotFoundError):
        other.admin.tenant.users.revoke_invitation(invite.id)
    assert all(u.id != invite.id for u in other.admin.tenant.users.list())
    # Policies are per tenant.
    shop.admin.tenant.recommendation_policy.update(diversity_enabled=True, max_per_category=1)
    assert other.admin.tenant.recommendation_policy.get().max_per_category != 1 or (
        not other.admin.tenant.recommendation_policy.get().configured
    )
    assert other.admin.tenant.usage.trends().tenant_id == str(other.id)
    # Recommendations never leak another tenant's catalog.
    recs = other.store.storefront.recommendations.get(user_id="u-1", top_n=5)
    assert "iso-1" not in recs.product_ids


def test_scope_enforcement(shop: Tenant) -> None:
    with pytest.raises(g.PermissionDeniedError):
        shop.store.tenant.training_jobs.create()
    with pytest.raises(g.PermissionDeniedError):
        shop.store.tenant.model_versions.list()
    with pytest.raises(g.PermissionDeniedError):
        shop.store.tenant.retraining_policy.update(schedule_enabled=True)


def test_async_client_against_the_app(shop: Tenant) -> None:
    async def run() -> None:
        tokens = _login(shop.email)
        transport = httpx.ASGITransport(app=app)
        async with g.AsyncGraphRec(
            base_url=BASE_URL,
            access_token=tokens,
            http_client=httpx.AsyncClient(transport=transport, base_url=BASE_URL),
            use_env=False,
        ) as client:
            assert (await client.tenant.recommendation_policy.get()).tenant_id == shop.id
            assert (await client.tenant.deployment.scaling(limit=1)).limitation
            assert (await client.tenant.usage.trends()).granularity == "day"
            assert (await client.tenant.users.list()).total >= 1
            await client.tenant.auth.logout()

    asyncio.run(run())


def _login(email: str) -> str:
    with TestClient(app, base_url=BASE_URL) as http:
        return _public(http).tenant.auth.login(email=email, password=PASSWORD).access_token


def test_zz_every_route_succeeded_at_least_once() -> None:
    """Runs last: each SDK route completed a real happy-path call in this module."""

    missing = set(g.ROUTES) - SUCCEEDED
    assert not missing, f"routes without a successful live call: {sorted(missing)}"
