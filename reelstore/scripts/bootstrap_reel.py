"""Create or update the Reel tenant end to end, through the GraphRec SDK, and write .env.

Supports:
- Idempotent execution (reuses existing Reel tenant if present, unless --new-tenant).
- Secret masking in terminal output.
- --teardown flag to suspend the tenant and clean local state.
- Offline checkpoint import or online training.

Usage:
    python scripts/bootstrap_reel.py --platform-token $PLATFORM_ADMIN_TOKEN
    python scripts/bootstrap_reel.py --teardown --platform-token $PLATFORM_ADMIN_TOKEN
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from graphrec_sdk import STOREFRONT_KEY_SCOPES, GraphRec

HERE = Path(__file__).resolve().parents[1]
ARTIFACT_NAME = "dgsr_movielens_32m"
PRODUCT_CHUNK = 500
EVENT_CHUNK = 200


def step(title: str) -> None:
    print(f"\n== {title}", flush=True)


def mask(value: Optional[str]) -> str:
    """Mask secrets to prevent leaking credentials in terminal or CI logs."""
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def env_value(value: object) -> str:
    """Quote values a shell or Compose would split (e.g. the tenant name "Reel 3f2a1c")."""
    text = str(value)
    return f'"{text}"' if any(c in text for c in ' #"\'$`') else text


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"\'')
    return out


def write_env(path: Path, updates: dict) -> None:
    quoted_updates = {key: env_value(value) for key, value in updates.items()}
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen = set()
    out = []
    for line in lines:
        line_clean = line.strip()
        if line_clean and not line_clean.startswith("#") and "=" in line_clean:
            key = line_clean.split("=", 1)[0].strip()
            if key in quoted_updates:
                out.append(f"{key}={quoted_updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    out += [f"{k}={v}" for k, v in quoted_updates.items() if k not in seen]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("GRAPHREC_BASE_URL", "http://localhost:8010"))
    parser.add_argument("--platform-token", default=os.environ.get("PLATFORM_ADMIN_TOKEN", ""))
    parser.add_argument("--name", default="Reel")
    parser.add_argument("--env-file", default=str(HERE / ".env"))
    parser.add_argument("--new-tenant", action="store_true", help="force creating a new tenant even if one exists")
    parser.add_argument("--teardown", action="store_true", help="suspend the Reel tenant and clear local state")
    parser.add_argument("--train", action="store_true",
                        help="train DGSR on the tenant's own events instead of importing the MovieLens checkpoint "
                             "(for hosts without model_artifacts/; personas then get a much smaller model)")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    existing_env = read_env(env_path)
    platform_token = args.platform_token or existing_env.get("PLATFORM_ADMIN_TOKEN", "")

    if not platform_token:
        raise SystemExit("Pass --platform-token (or set PLATFORM_ADMIN_TOKEN): required for tenant administration.")

    operator = GraphRec(base_url=args.base_url, access_token=platform_token, use_env=False)
    public = GraphRec(base_url=args.base_url, use_env=False)

    step(f"health @ {args.base_url}")
    print(public.health())

    # --- TEARDOWN MODE ---
    if args.teardown:
        step("teardown Reel tenant")
        tenant_id = existing_env.get("REEL_TENANT_ID")
        target_tenant = None
        all_tenants = operator.platform.tenants.list()

        if tenant_id:
            target_tenant = next((t for t in all_tenants if str(t.id) == tenant_id), None)
        if not target_tenant:
            target_tenant = next((t for t in all_tenants if t.name == args.name or t.name.startswith(f"{args.name} ")), None)

        if target_tenant:
            operator.platform.tenants.set_status(target_tenant.id, "suspended", reason="Reel teardown requested")
            print(f"Suspended tenant {target_tenant.id} ({target_tenant.name})")
        else:
            print("No matching Reel tenant found to suspend.")

        live = HERE / "state" / "live_events.jsonl"
        if live.is_file():
            live.unlink()
            print("Cleared state/live_events.jsonl")

        if env_path.is_file():
            # Remove tenant credentials from .env
            remaining = {k: v for k, v in existing_env.items() if not k.startswith("REEL_") and k != "GRAPHREC_API_KEY"}
            write_env(env_path, remaining)
            print(f"Cleaned Reel credentials from {env_path}")

        step("teardown complete")
        return 0

    # --- SETUP / IDEMPOTENT RUN ---
    films = json.loads((HERE / "data" / "films.json").read_text(encoding="utf-8"))
    personas = json.loads((HERE / "data" / "personas.json").read_text(encoding="utf-8"))

    existing_tenant = None
    if not args.new_tenant:
        all_tenants = operator.platform.tenants.list()
        tid = existing_env.get("REEL_TENANT_ID")
        if tid:
            existing_tenant = next((t for t in all_tenants if str(t.id) == tid and t.status == "active"), None)
        if not existing_tenant:
            existing_tenant = next((t for t in all_tenants if (t.name == args.name or t.name.startswith(f"{args.name} ")) and t.status == "active"), None)

    admin = None
    tenant = None
    email = existing_env.get("REEL_ADMIN_EMAIL")
    password = existing_env.get("REEL_ADMIN_PASSWORD")

    if existing_tenant and email and password:
        step(f"reusing existing active tenant: {existing_tenant.id} ({existing_tenant.name})")
        try:
            admin = public.with_credentials(email=email, password=password)
            # Verify credentials by listing model versions
            admin.tenant.model_versions.list()
            tenant = existing_tenant
            print(f"Authenticated as tenant admin: {email} (secret: {mask(password)})")
        except Exception as exc:
            print(f"Existing credentials could not be reused ({exc}); proceeding to register or reset...")
            admin = None

    if admin is None:
        suffix = secrets.token_hex(3)
        email = f"reel-{suffix}@example.org"
        password = "reel-" + secrets.token_urlsafe(18)

        step("register tenant")
        tenant = public.tenant.auth.register(name=f"{args.name} {suffix}", admin_email=email)
        public.tenant.auth.setup_password(setup_token=tenant.setup_token, password=password, email=email)
        admin = public.with_credentials(email=email, password=password)
        print(f"tenant {tenant.id}  admin {email}  password {mask(password)}")

    step("quota override (platform operator)")
    operator.platform.tenants.set_quota_override(tenant.id, overrides={"stored_products": 10_000, "training_jobs": 10})
    print("Quota set: stored_products=10,000, training_jobs=10")

    step("storefront API key")
    api_key_str = existing_env.get("GRAPHREC_API_KEY", "")
    key_valid = False
    if api_key_str and not args.new_tenant:
        try:
            test_client = GraphRec(base_url=args.base_url, api_key=api_key_str, use_env=False)
            test_client.storefront.recommendations.for_session("test-probe", top_n=1)
            key_valid = True
            print(f"Reusing existing valid storefront API key: {mask(api_key_str)}")
        except Exception:
            key_valid = False

    if not key_valid:
        key = admin.tenant.api_keys.create(name="reel-storefront", scopes=STOREFRONT_KEY_SCOPES)
        api_key_str = key.secret
        print(f"Created new storefront API key: {mask(api_key_str)} scopes={list(key.scopes)}")

    step(f"catalogue: {len(films)} films")
    for start in range(0, len(films), PRODUCT_CHUNK):
        chunk = films[start : start + PRODUCT_CHUNK]
        result = admin.tenant.catalog.bulk_upsert([
            {
                "external_id": f["id"],
                "title": f"{f['title']} ({f['year']})" if f["year"] else f["title"],
                "category": f["genres"][0] if f["genres"] else "Other",
                "price": "0",
                "metadata": {"source": "MovieLens 32M", "genres": f["genres"], "year": f["year"], "tmdb_id": f["tmdbId"]},
            }
            for f in chunk
        ])
        print(f"  {start + len(chunk):>5}/{len(films)}  created={result.created_count} updated={result.updated_count} "
              f"rejected={result.rejected_count}")

    step("persona histories (real training events, original timestamps)")
    for p in personas:
        events = [
            {
                "event_id": f"ml-{p['user_id']}-{n}",
                "event_type": "rating",
                "user_id": p["user_id"],
                "external_product_id": h["filmId"],
                "occurred_at": datetime.fromtimestamp(h["time"], timezone.utc),
                "context": {"source": "movielens-training-history"},
            }
            for n, h in enumerate(p["history"])
        ]
        for start in range(0, len(events), EVENT_CHUNK):
            r = admin.storefront.events.create_batch(events[start : start + EVENT_CHUNK])
            print(f"  {p['name']:<5} {start + EVENT_CHUNK if start + EVENT_CHUNK < len(events) else len(events):>3}/{len(events)}  {r}")

    step("model version resolution")
    active_version = None
    if not args.new_tenant:
        versions = admin.tenant.model_versions.list()
        active_version = next((v for v in versions if v.status == "active"), None)
        if active_version:
            print(f"Reusing already active model version: {active_version.id} ({getattr(active_version, 'version_tag', '')})")

    if not active_version:
        step("train DGSR on the persona histories" if args.train else "import the offline DGSR checkpoint and activate it")
        snapshot = admin.tenant.datasets.create_snapshot(description="Reel persona histories")
        configuration = {"mode": "train", "epochs": 2} if args.train else {"pretrained_artifact": ARTIFACT_NAME}
        job = admin.tenant.training_jobs.create(dataset_snapshot_id=snapshot.id, configuration=configuration)
        job = admin.tenant.training_jobs.wait(job.id, timeout=600, poll_interval=2)
        if job.status != "succeeded" or not job.model_version_id:
            raise SystemExit(f"Model creation failed: {job.status} {getattr(job, 'failure_reason', '')}")
        active_version = admin.tenant.model_versions.activate(job.model_version_id)
        print(f"Activated new version: {active_version.id} ({getattr(active_version, 'version_tag', '')})")

    step("smoke test: one recommendation per persona")
    shop = GraphRec(base_url=args.base_url, api_key=api_key_str, use_env=False)
    titles = {f["id"]: f["title"] for f in films}
    for p in personas:
        recs = shop.storefront.recommendations.get(user_id=p["user_id"], top_n=5)
        print(f"  {p['name']:<5} {recs.strategy:<13} " + " | ".join(titles.get(i, i) for i in recs.product_ids))

    write_env(env_path, {
        "GRAPHREC_BASE_URL": args.base_url,
        "GRAPHREC_API_KEY": api_key_str,
        "REEL_TENANT_NAME": tenant.name,
        "REEL_ADMIN_EMAIL": email,
        "REEL_ADMIN_PASSWORD": password,
        "REEL_TENANT_ID": str(tenant.id),
        "REEL_MODEL_VERSION_ID": str(active_version.id),
        "REEL_MODEL_VERSION_TAG": str(getattr(active_version, "version_tag", "") or ""),
        "REEL_MODEL_SOURCE": "trained" if args.train else "checkpoint",
    })
    step(f"done - wrote {env_path}. Start: uvicorn app.main:app --port 5290")
    return 0


if __name__ == "__main__":
    sys.exit(main())
