"""End-to-end smoke test against a running GraphRec stack (docker compose up).

Creates a throw-away tenant and walks every major SDK area. Run it after
changing the API or the SDK:

    python examples/end_to_end_smoke.py --base-url http://localhost:8010
"""

from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import graphrec_sdk as g
from graphrec_sdk.ecommerce import CatalogSync, EventTracker, RecommendationSession


def step(title: str) -> None:
    print(f"\n== {title}")


def main(base_url: str, platform_token: Optional[str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    email, password = f"smoke-{suffix}@example.org", f"smoke-password-{suffix}"

    with g.GraphRec(base_url=base_url, use_env=False) as public:
        step("health")
        print(public.health())
        step("register tenant")
        tenant = public.tenants.register(name=f"SDK Smoke {suffix}", admin_email=email)
        print(tenant.id, tenant.status)
        assert tenant.setup_token, "registration must return a one-time setup token"
        public.auth.setup_password(setup_token=tenant.setup_token, password=password, email=email)
        step("setup token is single-use")
        try:
            public.auth.setup_password(setup_token=tenant.setup_token, password="another-password")
        except g.AuthenticationError as exc:
            assert exc.code == "invalid_setup_token", exc.code
            print("reused token rejected:", exc.code)
        else:
            raise AssertionError("a used setup token was accepted")

        admin = public.with_credentials(email=email, password=password)
        step("subscription & usage")
        print(
            admin.subscription.get().plan_code,
            len(admin.usage.get().dimensions),
            "usage dimensions",
        )

        step("API key lifecycle")
        key = admin.api_keys.create(name=f"smoke-{suffix}", scopes=g.STOREFRONT_KEY_SCOPES)
        rotated = admin.api_keys.rotate(key.id, reason="smoke test", grace_period_seconds=60)
        assert rotated.secret != key.secret
        print([k.prefix for k in admin.api_keys.list()])

        store = public.with_credentials(api_key=rotated.secret)
        step("catalog")
        catalog = [
            {
                "external_id": f"sku-{i}",
                "title": f"Product {i}",
                "price": f"{10 + i}.00",
                "category": ["shirts", "shoes"][i % 2],
            }
            for i in range(60)
        ]
        print(CatalogSync(store).run(catalog).summary())
        store.products.update("sku-1", price="9.99")
        store.products.disable("sku-59")

        step("events")
        with EventTracker(store, batch_size=25) as tracker:
            for i in range(120):
                user = f"user-{i % 12}"
                tracker.view(user, f"sku-{i % 60}")
                if i % 5 == 0:
                    tracker.purchase(user, f"sku-{i % 60}", order_id=f"ORD-{i}")
        print([b.accepted_count for b in store.events.list_batches()][:5])

        step("scope enforcement")
        try:
            store.model_versions.list()
        except g.PermissionDeniedError as exc:
            print("storefront key cannot read the model registry:", exc.code)
        else:
            raise AssertionError("a storefront key without models:read listed model versions")

        step("dataset upload & snapshot")
        csv = "event_id,event_type,user_id,external_product_id\n" + "".join(
            f"csv-{suffix}-{i},click,user-{i % 7},sku-{i % 30}\n" for i in range(50)
        )
        upload = admin.datasets.upload((f"events-{suffix}.csv", csv.encode()))
        print(
            "uploaded",
            upload.accepted_events,
            "events; snapshot",
            upload.dataset_snapshot.checksum[:12],
        )
        snapshot = admin.datasets.create_snapshot(cutoff_at=datetime.now(timezone.utc))

        step("training & activation")
        job = admin.training_jobs.create(dataset_snapshot_id=snapshot.id)
        job = admin.training_jobs.wait(job.id, timeout=300, poll_interval=2)
        assert job.model_version_id is not None, job
        version = admin.model_versions.activate(job.model_version_id)
        print(version.version_tag, version.status, admin.deployment.get().status)
        print("p95", admin.metrics.summary().p95_latency_ms, "ms")

        step("recommendations & feedback")
        widget = RecommendationSession(store)
        recs = widget.recommend(user_id="user-1", top_n=5, exclude_product_ids=["sku-0"])
        assert "sku-0" not in recs.product_ids and "sku-59" not in recs.product_ids
        print(recs.strategy, recs.product_ids)
        if recs.items:
            widget.click(recs, recs.items[0].external_product_id)
            widget.convert(recs, recs.items[0].external_product_id, value="12.00")
        anon = store.recommendations.for_session(
            "sess-smoke", recent_product_ids=["sku-3"], top_n=3
        )
        print("session:", anon.product_ids)

        if platform_token:
            step("platform administration")
            ops = public.with_credentials(access_token=platform_token)
            print(ops.platform.status())
            print(
                ops.platform.get_tenant(tenant.id).status,
                len(ops.platform.list_audit_logs()),
                "audit records",
            )

        step("cleanup")
        admin.api_keys.revoke(key.id)
        print("revoked", key.prefix)
        admin.close()
        store.close()
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8010")
    parser.add_argument("--platform-token", default=os.environ.get("PLATFORM_ADMIN_TOKEN"))
    args = parser.parse_args()
    main(args.base_url, args.platform_token)
