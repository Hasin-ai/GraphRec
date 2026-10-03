"""End-to-end user stories for every SRS role, on the Amazon Beauty dataset.

Runs against a live stack (``docker compose up``) with the pretrained DGSR
artifact mounted (``MODEL_ARTIFACT_DIR``). Each step is one user-story clause
from ``USER_STORIES.md``; a failed assertion names the clause. Nothing is
mocked: a fresh tenant is registered, Beauty.csv is uploaded through the API,
the checkpoint is imported as a model version, and recommendations are served
by the real model.

    python tests/e2e/beauty_e2e.py --base-url http://localhost:8010 \
        --dataset dgsr_notebooks/Beauty.csv --artifact dgsr_beauty_t4_v2 \
        --platform-token "$PLATFORM_ADMIN_TOKEN" --write-storefront-env

Exit code 0 only when every story passes. A JSON report is written to
``tests/e2e/results/beauty_e2e_report.json``.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import graphrec_sdk as g
from graphrec_sdk.ecommerce import EventTracker, RecommendationSession

REPO = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / "results"
PERSONAS = {"maya": "112", "noah": "40", "lina": "0"}
PERSONA_BLURBS = {
    "maya": "Beauty shopper 112 - the longest history in the dataset",
    "noah": "Beauty shopper 40 - a regular with a mid-sized history",
    "lina": "Beauty shopper 0 - the notebook's reference user",
}


class Story:
    """Collects pass/fail per clause and prints as it goes."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.failures = 0

    def check(self, role: str, clause: str, condition: bool, detail: Any = None) -> bool:
        status = "PASS" if condition else "FAIL"
        if not condition:
            self.failures += 1
        self.records.append({"role": role, "clause": clause, "status": status, "detail": _jsonable(detail)})
        suffix = f"  -> {detail}" if detail is not None else ""
        print(f"  [{status}] {clause}{suffix}", flush=True)
        return condition

    def expect_error(self, role: str, clause: str, call: Callable[[], Any], error: type | tuple[type, ...], code: str | None = None) -> None:
        try:
            call()
        except error as exc:
            got = getattr(exc, "code", None)
            self.check(role, clause, code is None or got == code, f"{type(exc).__name__} {got}")
        except Exception as exc:  # noqa: BLE001
            self.check(role, clause, False, f"unexpected {type(exc).__name__}: {exc}")
        else:
            self.check(role, clause, False, "no error raised")


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def notebook_reference(artifact_dir: Path) -> list[str]:
    path = artifact_dir / "recommendations_user_0.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return [row["item_id"] for row in csv.DictReader(handle)]


def user_history(dataset: Path, user_id: str) -> list[str]:
    rows = []
    with dataset.open(encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            if row["user_id"] == user_id:
                rows.append((int(row["time"]), index, row["item_id"]))
    rows.sort()
    return [item for _, _, item in rows]


def write_storefront_env(values: dict[str, str]) -> Path:
    env_path = REPO / "apps" / "demo-storefront" / ".env"
    example = REPO / "apps" / "demo-storefront" / ".env.example"
    lines = (env_path if env_path.is_file() else example).read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return env_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("GRAPHREC_BASE_URL", "http://localhost:8010"))
    parser.add_argument("--dataset", default=str(REPO / "dgsr_notebooks" / "Beauty.csv"))
    parser.add_argument("--artifact", default="dgsr_beauty_t4_v2", help="name under MODEL_ARTIFACT_DIR")
    parser.add_argument("--artifact-dir", default=str(REPO / "model_artifacts" / "dgsr_beauty_t4_v2"))
    parser.add_argument("--platform-token", default=os.environ.get("PLATFORM_ADMIN_TOKEN"))
    parser.add_argument("--write-storefront-env", action="store_true")
    parser.add_argument("--latency-samples", type=int, default=40)
    args = parser.parse_args()

    dataset = Path(args.dataset)
    if not dataset.is_file():
        print(f"dataset not found: {dataset}", file=sys.stderr)
        return 2
    story = Story()
    suffix = uuid.uuid4().hex[:6]
    started = time.time()
    report: dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat(), "base_url": args.base_url}

    with g.GraphRec(base_url=args.base_url, use_env=False, timeout=900.0) as public:
        # ------------------------------------------------------------------ owner / admin
        section("Tenant Business Owner registers the business (NR-F-01)")
        admin_email = f"owner-{suffix}@beauty.example"
        admin_password = f"Owner-{uuid.uuid4().hex}"
        tenant = public.tenant.auth.register(name=f"Beauty Shop {suffix}", admin_email=admin_email)
        story.check("owner", "registration returns an active tenant and a one-time setup token", tenant.status == "active" and bool(tenant.setup_token), tenant.id)
        public.tenant.auth.setup_password(setup_token=tenant.setup_token, password=admin_password, email=admin_email)
        story.expect_error("owner", "the setup token cannot be reused", lambda: public.tenant.auth.setup_password(setup_token=tenant.setup_token, password="x" * 20), g.AuthenticationError, "invalid_setup_token")
        admin = public.with_credentials(email=admin_email, password=admin_password)
        login = public.tenant.auth.login(email=admin_email, password=admin_password)
        story.check("admin", "login grants the tenant_administrator role (NR-F-02)", login.user_role == "tenant_administrator", sorted(login.scopes)[:4])
        story.expect_error("admin", "a wrong password is rejected", lambda: public.tenant.auth.login(email=admin_email, password="wrong-password-123"), g.AuthenticationError)

        section("Tenant Administrator configures authorized users (SRS 2.7)")
        dev_email = f"dev-{suffix}@beauty.example"
        invite = admin.tenant.users.invite(dev_email, role="tenant_developer", display_name="Integration dev")
        story.check("admin", "inviting a developer returns an invited user with a setup token", invite.status == "invited" and bool(invite.setup_token), invite.role)
        story.expect_error("admin", "the same address cannot be invited twice", lambda: admin.tenant.users.invite(dev_email), g.ConflictError)
        users = admin.tenant.users.list()
        story.check("admin", "the user list shows the administrator and the developer", {u.email for u in users} == {admin_email, dev_email}, users.total)

        # ------------------------------------------------------------------ developer
        section("Tenant Developer activates the account and connects the store (NR-F-03)")
        dev_password = f"Dev-{uuid.uuid4().hex}"
        public.tenant.auth.setup_password(setup_token=invite.setup_token, password=dev_password, email=dev_email)
        dev_login = public.tenant.auth.login(email=dev_email, password=dev_password)
        story.check("developer", "login grants the tenant_developer role with limited scopes", dev_login.user_role == "tenant_developer" and "training:write" not in dev_login.scopes, sorted(dev_login.scopes))
        developer = public.with_credentials(email=dev_email, password=dev_password)
        story.expect_error("developer", "a developer cannot invite users", lambda: developer.tenant.users.invite(f"x-{suffix}@beauty.example"), g.PermissionDeniedError)
        story.expect_error("developer", "a developer cannot request training", lambda: developer.tenant.training_jobs.create(), g.PermissionDeniedError, "insufficient_scope")
        store_key = developer.tenant.api_keys.create(name=f"storefront-{suffix}", scopes=g.STOREFRONT_KEY_SCOPES)
        story.check("developer", "creates the storefront credential", store_key.status == "active" and store_key.secret.startswith("gr_live_"), store_key.prefix)
        story.expect_error("developer", "a developer cannot delegate training scopes to a key", lambda: developer.tenant.api_keys.create(name="too-wide", scopes=["training:write"]), g.PermissionDeniedError)
        rotated = developer.tenant.api_keys.rotate(store_key.id, reason="rotation drill", grace_period_seconds=120)
        story.check("developer", "rotates the credential with a grace period", rotated.secret != store_key.secret and rotated.grace_expires_at is not None, rotated.prefix)
        keys = developer.tenant.api_keys.list()
        story.check("developer", "views credential status", any(k.id == store_key.id and k.status == "active" for k in keys), [k.prefix for k in keys])
        store = public.with_credentials(api_key=rotated.secret)

        section("Tenant Developer uploads the Beauty interaction log (NR-F-05, NR-F-06)")
        t0 = time.time()
        upload = developer.tenant.datasets.upload(dataset)
        elapsed = time.time() - t0
        story.check("developer", "57,289 items became products and 394,908 interactions became events", upload.accepted_products == 57289 and upload.accepted_events == 394908, f"{upload.accepted_products} products, {upload.accepted_events} events in {elapsed:.1f}s")
        story.check("developer", "the upload produced a dataset snapshot with the right counts (ER-F-01)", upload.dataset_snapshot.event_count == 394908 and upload.dataset_snapshot.user_count == 52204, upload.dataset_snapshot.id)
        report["upload_seconds"] = round(elapsed, 1)
        replay = developer.tenant.datasets.upload(dataset)
        story.check("developer", "re-uploading the same log records no new events (NR-NF-05)", replay.accepted_events == 0 and replay.accepted_products == 0, f"{replay.accepted_events} new events")
        batches = store.storefront.events.list_batches()
        story.check("app", "submission status is visible per batch", any(b.accepted_count == 394908 for b in batches), [(b.accepted_count, b.duplicate_count) for b in batches[:3]])

        # ------------------------------------------------------------------ e-commerce application: catalog
        section("Tenant E-Commerce Application manages the catalog (NR-F-04)")
        page = store.tenant.catalog.list(limit=100)
        story.check("app", "products are paginated with a total", len(page) == 100 and page.total == 57289, page.total)
        lookup = store.tenant.catalog.list(external_ids=["0", "1", "54410"])
        story.check("app", "products can be fetched by external id", {p.external_id for p in lookup} == {"0", "1", "54410"}, lookup.total)
        updated = store.tenant.catalog.update("54410", title="Vetiver Roll-On Oil", price="32.00", category="fragrance")
        story.check("app", "a product can be updated in place", updated.title == "Vetiver Roll-On Oil" and str(updated.price) == "32.00", updated.external_id)
        disabled_item = "42267"
        store.tenant.catalog.disable(disabled_item)
        story.check("app", "a product can be disabled", not store.tenant.catalog.get(disabled_item).is_active, disabled_item)
        story.expect_error("app", "an unknown product is a clear 404 (NR-NF-03)", lambda: store.tenant.catalog.get("does-not-exist"), g.NotFoundError)

        section("Tenant E-Commerce Application submits live events (NR-F-06, ER-F-04)")
        live_user = "112"
        with EventTracker(store, batch_size=10) as tracker:
            tracker.view(live_user, "0")
            tracker.add_to_cart(live_user, "1")
            tracker.purchase(live_user, "1", order_id=f"ORD-{suffix}")
        single = store.storefront.events.create("view", user_id=live_user, product_id="2", event_id=f"evt-{suffix}-1")
        duplicate = store.storefront.events.create("view", user_id=live_user, product_id="2", event_id=f"evt-{suffix}-1")
        story.check("app", "a repeated event id is reported as a duplicate, not stored twice", single.duplicate is False and duplicate.duplicate is True, duplicate.event_id)

        # ------------------------------------------------------------------ admin: training & activation
        section("Tenant Administrator trains and reviews the model (NR-F-07..NR-F-11)")
        story.expect_error("app", "a storefront key cannot start training (NR-F-02 role-appropriate access)", lambda: store.tenant.training_jobs.create(), g.PermissionDeniedError, "insufficient_scope")
        snapshot = admin.tenant.datasets.create_snapshot(cutoff_at=datetime.now(timezone.utc))
        story.check("admin", "an explicit snapshot is created from this tenant's data only (BRULE-12)", snapshot.event_count >= 394908 and snapshot.product_count >= 57288, snapshot.id)
        story.expect_error("admin", "importing an artifact that does not exist is a clear 404", lambda: admin.tenant.training_jobs.create(dataset_snapshot_id=snapshot.id, configuration={"pretrained_artifact": "no-such-artifact"}), g.NotFoundError)
        job = admin.tenant.training_jobs.create(dataset_snapshot_id=snapshot.id, configuration={"pretrained_artifact": args.artifact})
        job = admin.tenant.training_jobs.wait(job.id, timeout=600, poll_interval=2)
        story.check("admin", "the DGSR checkpoint import succeeds and yields a model version (NR-F-08)", job.status == "succeeded" and job.model_version_id is not None, f"{job.status} {job.failure_reason or ''}")
        version = admin.tenant.model_versions.get(job.model_version_id)
        source = version.tenant.metrics.get("source", {})
        story.check("admin", "the version carries offline quality (validation NDCG@10 > 0.3) (ER-F-03, NR-F-09)", version.tenant.metrics.get("validation", {}).get("NDCG@10", 0) > 0.3, version.tenant.metrics.get("validation"))
        story.check("admin", "the artifact is verified against the tenant catalog and shoppers (ER-NF-03)", source.get("catalog_item_coverage", 0) >= 0.99 and source.get("event_user_coverage", 0) >= 0.99, {k: source.get(k) for k in ("catalog_item_coverage", "event_user_coverage", "checkpoint_sha256")})
        story.check("admin", "the version is eligible before activation", version.status == "eligible", version.version_tag)
        active = admin.tenant.model_versions.activate(version.id)
        story.check("admin", "activation makes exactly one version active (NR-F-10, BRULE-08)", active.status == "active" and sum(1 for v in admin.tenant.model_versions.list() if v.status == "active") == 1, active.version_tag)
        deployment = admin.tenant.deployment.get()
        story.check("admin", "active-model and service status are visible (NR-F-16)", deployment.status == "available" and deployment.active_model_version_id == version.id and deployment.last_transition_at is not None, {"status": deployment.status, "since": str(deployment.last_transition_at)})

        # ------------------------------------------------------------------ e-commerce application: recommendations
        section("Tenant E-Commerce Application requests recommendations (NR-F-12, NR-F-13, ER-F-05)")
        widget = RecommendationSession(store)
        reference = notebook_reference(Path(args.artifact_dir))
        recs0 = widget.recommend(user_id="0", top_n=10)
        story.check("app", "a known shopper is served by the active DGSR version", recs0.strategy == "personalized" and recs0.model_version_id == version.id and not recs0.fallback_used, recs0.product_ids)
        if reference:
            expected = [item for item in reference if item != disabled_item][:10]
            got = recs0.product_ids[: len(expected)]
            overlap = len(set(expected) & set(got))
            story.check("app", "the API ranking matches the notebook's recommendations for user 0 (ER-NF-06)", got == expected or overlap >= 9, f"overlap {overlap}/{len(expected)}")
        story.check("app", "a disabled product is never recommended (BRULE-09)", disabled_item not in recs0.product_ids, disabled_item)
        again = widget.recommend(user_id="0", top_n=10)
        story.check("app", "identical requests give identical ordering (ER-NF-06)", again.product_ids == recs0.product_ids)
        scarce_item = recs0.product_ids[0]
        store.tenant.catalog.update(scarce_item, availability_status=g.AvailabilityStatus.OUT_OF_STOCK)
        scarce = widget.recommend(user_id="0", top_n=10)
        story.check("app", "an out-of-stock product is never recommended (BRULE-09)", scarce_item not in scarce.product_ids, scarce_item)
        store.tenant.catalog.update(scarce_item, availability_status=g.AvailabilityStatus.AVAILABLE)
        rankings = {}
        for persona, uid in PERSONAS.items():
            rankings[persona] = widget.recommend(user_id=uid, top_n=10).product_ids
        distinct = len({tuple(r) for r in rankings.values()})
        story.check("app", "shoppers with different histories receive different rankings", distinct == 3, {k: v[:3] for k, v in rankings.items()})
        excluded = rankings["lina"][:2]
        filtered = widget.recommend(user_id="0", top_n=10, exclude_product_ids=excluded)
        story.check("app", "excluded products are honoured", not set(excluded) & set(filtered.product_ids), excluded)
        history0 = user_history(dataset, "0")
        story.check("app", "already-purchased items are not recommended again", not set(history0) & set(recs0.product_ids), len(history0))
        session = store.storefront.recommendations.for_session(f"sess-{suffix}", recent_product_ids=history0[-5:], top_n=10)
        story.check("app", "an anonymous session with recent items gets model-based session recommendations (XR-F-01)", session.strategy == "session" and not session.fallback_used and session.model_version_id == version.id, session.product_ids[:5])
        empty = store.storefront.recommendations.for_session(f"sess-empty-{suffix}", top_n=5)
        story.check("app", "a session with nothing known gets an explicit tenant-safe fallback (ER-F-10, XR-F-09)", empty.fallback_used and empty.strategy == "popular_fallback" and len(empty.items) == 5, empty.fallback_tier)
        unknown = widget.recommend(user_id=f"never-seen-{suffix}", top_n=5)
        story.check("app", "an unknown shopper without history gets the fallback, labelled as such", unknown.fallback_used and unknown.strategy == "popular_fallback", unknown.strategy)
        live = widget.recommend(user_id=live_user, top_n=10)
        story.check("app", "new live events are folded into a known shopper's history (XR-F-01)", live.strategy == "personalized" and "1" not in live.product_ids and "2" not in live.product_ids, live.product_ids[:5])

        section("Recommendation latency (NR-NF-04 target: P95 < 300 ms)")
        samples = []
        sample_users = [PERSONAS["lina"], PERSONAS["noah"], PERSONAS["maya"], "2", "5"]
        for i in range(args.latency_samples):
            t0 = time.perf_counter()
            widget.recommend(user_id=sample_users[i % len(sample_users)], top_n=10)
            samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        p50 = statistics.median(samples)
        p95 = samples[int(len(samples) * 0.95) - 1]
        story.check("app", "P95 end-to-end latency below 300 ms", p95 < 300, f"p50 {p50:.0f} ms, p95 {p95:.0f} ms over {len(samples)} requests")
        report["latency_ms"] = {"p50": round(p50, 1), "p95": round(p95, 1), "samples": len(samples)}

        section("Tenant E-Commerce Application reports feedback (NR-F-14)")
        impression = widget.impression(recs0)
        click = widget.click(recs0, recs0.items[0].external_product_id)
        conversion = widget.convert(recs0, recs0.items[0].external_product_id, value="32.00")
        story.check("app", "impression, click and conversion feedback are accepted", impression.accepted and click.accepted and conversion.accepted, (impression.event_id, click.event_id, conversion.event_id))
        story.expect_error("app", "a storefront key cannot read the model registry", lambda: store.tenant.model_versions.list(), g.PermissionDeniedError, "insufficient_scope")

        # ------------------------------------------------------------------ admin: lifecycle
        section("Tenant Administrator manages versions (NR-F-11, ER-F-06, ER-F-07)")
        job2 = admin.tenant.training_jobs.wait(admin.tenant.training_jobs.create(dataset_snapshot_id=snapshot.id, configuration={"pretrained_artifact": args.artifact}).id, timeout=600, poll_interval=2)
        second = admin.tenant.model_versions.activate(job2.model_version_id)
        story.check("admin", "activating a second version retires the first", second.status == "active" and admin.tenant.model_versions.get(version.id).status == "retired", second.version_tag)
        served = widget.recommend(user_id="0", top_n=5)
        story.check("app", "serving follows the newly active version", served.model_version_id == second.id, served.model_version_id)
        rolled = admin.tenant.model_versions.rollback(version.id)
        story.check("admin", "rollback re-activates the historical version", rolled.status == "active" and rolled.id == version.id and widget.recommend(user_id="0", top_n=5).model_version_id == version.id)
        story.expect_error("admin", "rollback to a version of another tenant or an unknown id is rejected", lambda: admin.tenant.model_versions.rollback(uuid.uuid4()), g.NotFoundError)
        story.expect_error("admin", "the active version cannot be archived", lambda: admin.tenant.model_versions.archive(version.id), g.ConflictError)
        archived = admin.tenant.model_versions.archive(second.id)
        story.check("admin", "a retired version can be archived", archived.status == "archived", archived.version_tag)
        jobs = admin.tenant.training_jobs.list()
        story.check("admin", "training history lists both imports with their configuration (NR-F-08)", sum(1 for j in jobs if j.status == "succeeded" and j.configuration.get("mode") == "pretrained_import") >= 2, [(j.status, j.configuration.get("pretrained_artifact")) for j in jobs[:4]])

        section("Tenant Administrator monitors usage and status (NR-F-15, NR-F-16, ER-F-08)")
        usage = admin.tenant.usage.get()
        dims = {d.type: d for d in usage.dimensions}
        events_used = float(getattr(dims.get("accepted_events"), "used", 0) or 0)
        story.check("admin", "usage records the accepted events and training jobs", events_used >= 394908 and "training_jobs" in dims, {k: str(getattr(v, "used", None)) for k, v in dims.items()})
        subscription = admin.tenant.subscription.get()
        story.check("admin", "the plan and its limits are visible", bool(subscription.plan_code), subscription.plan_code)
        story.check("admin", "the recommendation requests just served are metered", float(getattr(dims.get("recommendation_requests"), "used", 0) or 0) > 0, str(getattr(dims.get("recommendation_requests"), "used", None)))
        metrics = admin.tenant.metrics.summary()
        story.check("admin", "the metrics summary measures the requests just served (NR-F-16)", metrics.request_count > 0 and metrics.p95_latency_ms is not None and metrics.error_rate == 0.0, {"requests": metrics.request_count, "p95_ms": metrics.p95_latency_ms, "error_rate": metrics.error_rate, "fallback_rate": metrics.fallback_rate})
        story.check("admin", "the summary reports the active version's own offline quality", metrics.quality is not None and metrics.quality.model_version_id == version.id, getattr(metrics.quality, "version_tag", None))

        # ------------------------------------------------------------------ isolation
        section("Tenant isolation (NR-NF-01, BRULE-02)")
        other_email = f"other-{suffix}@example.org"
        other = public.tenant.auth.register(name=f"Other Shop {suffix}", admin_email=other_email)
        public.tenant.auth.setup_password(setup_token=other.setup_token, password=admin_password, email=other_email)
        other_admin = public.with_credentials(email=other_email, password=admin_password)
        other_key = other_admin.tenant.api_keys.create(name="probe", scopes=g.STOREFRONT_KEY_SCOPES)
        probe = public.with_credentials(api_key=other_key.secret)
        story.check("owner", "another tenant sees none of this tenant's products", probe.tenant.catalog.list().total == 0)
        story.expect_error("owner", "another tenant cannot read this tenant's product by id", lambda: probe.tenant.catalog.get("0"), g.NotFoundError)
        story.expect_error("owner", "another tenant cannot activate this tenant's model (BRULE-07)", lambda: other_admin.tenant.model_versions.activate(version.id), g.NotFoundError)
        other_recs = probe.storefront.recommendations.get(user_id="0", top_n=5)
        story.check("owner", "another tenant's request never sees this tenant's model", other_recs.model_version_id is None and other_recs.fallback_used, other_recs.strategy)

        # ------------------------------------------------------------------ platform administrator
        if args.platform_token:
            section("Platform Administrator operates the platform (ER-F-09, ER-F-11, ER-F-12)")
            ops = public.with_credentials(access_token=args.platform_token)
            status = ops.platform.status()
            story.check("platform", "platform status is reported", status.database == "connected", status.status)
            tenants = ops.platform.tenants.list()
            story.check("platform", "the new tenant is listed", any(str(t.id) == str(tenant.id) for t in tenants), len(tenants))
            plans = ops.platform.plans.list()
            story.check("platform", "pricing plans with limits are visible", len(plans) >= 3, [p.code for p in plans])
            override = ops.platform.tenants.set_quota_override(tenant.id, overrides={"accepted_events": 2_000_000})
            story.check("platform", "a quota override is stored for the tenant (BRULE-10)", override.overrides.get("accepted_events") == 2_000_000, override.overrides)
            suspended = ops.platform.tenants.set_status(tenant.id, "suspended")
            story.check("platform", "the tenant can be suspended", suspended.status == "suspended")
            story.expect_error("platform", "a suspended tenant's storefront credential is refused", lambda: store.tenant.catalog.list(limit=1), (g.AuthenticationError, g.PermissionDeniedError))
            restored = ops.platform.tenants.set_status(tenant.id, "active")
            story.check("platform", "the tenant can be restored and serves again", restored.status == "active" and store.tenant.catalog.list(limit=1).total == 57289)
            audit = ops.platform.list_audit_logs()
            story.check("platform", "administrative actions are audited (ER-F-11)", len(audit) > 0, len(audit))
            failures = ops.platform.list_failures()
            story.check("platform", "failure visibility is available", failures is not None, len(failures))
            story.expect_error("platform", "the platform token is not a tenant credential", lambda: ops.tenant.catalog.list(limit=1), (g.AuthenticationError, g.PermissionDeniedError))
        else:
            print("  (platform administrator stories skipped: no --platform-token)")

        # ------------------------------------------------------------------ hand-over to the storefront
        if args.write_storefront_env:
            section("Storefront hand-over")
            seed_key = admin.tenant.api_keys.create(name=f"seed-{suffix}", scopes=[
                "catalog:read", "catalog:write", "events:read", "events:write",
                "training:read", "training:write", "models:read", "models:write", "models:deploy", "recommendations:read",
            ])
            env_path = write_storefront_env({
                "GRAPHREC_BASE_URL": args.base_url,
                "GRAPHREC_API_KEY": rotated.secret,
                "GRAPHREC_SEED_API_KEY": seed_key.secret,
                "DEMO_PERSONA_USERS": ",".join(f"{k}={v}:{PERSONA_BLURBS[k]}" for k, v in PERSONAS.items()),
                "MODEL_PROOF_VERIFIED": "false",
                "MODEL_PROOF_VERSION_ID": "",
                "DEMO_ADMIN_EMAIL": admin_email,
                "DEMO_ADMIN_PASSWORD": admin_password,
                "DEMO_DEVELOPER_EMAIL": dev_email,
                "DEMO_DEVELOPER_PASSWORD": dev_password,
                "DEMO_TENANT_ID": str(tenant.id),
                "DEMO_MODEL_VERSION_ID": str(version.id),
            })
            print(f"  wrote {env_path}")

        report.update({
            "tenant_id": str(tenant.id),
            "administrator": admin_email,
            "developer": dev_email,
            "model_version_id": str(version.id),
            "model_metrics": version.metrics,
            "rankings": rankings,
        })
        admin.close(); developer.close(); store.close(); other_admin.close(); probe.close()

    report["clauses"] = story.records
    report["failures"] = story.failures
    report["seconds"] = round(time.time() - started, 1)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "beauty_e2e_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    total = len(story.records)
    print(f"\n{total - story.failures}/{total} clauses passed in {report['seconds']}s; report in {RESULTS / 'beauty_e2e_report.json'}")
    return 0 if story.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
