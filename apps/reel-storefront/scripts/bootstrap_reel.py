"""Create the Reel tenant end to end, through the GraphRec SDK, and write .env.

Steps (each is a real API call; nothing is faked):

1. Register tenant "Reel <suffix>", set the admin password.
2. Raise the tenant's stored-product quota (platform operator token) so the full
   7,951-film DGSR vocabulary fits; every recommendable film must be a product,
   or the API's eligibility filter drops it.
3. Create a storefront API key (catalog, events, recommendations scopes).
4. Sync the 7,951 films as products (real MovieLens titles and genres).
5. Submit each persona's full training history as events, with the original
   timestamps and event ids ``ml-<row>``, so the API reads exactly the history the
   checkpoint was trained on and serves the persona through the trained path.
6. Snapshot + "training" job that IMPORTS the offline checkpoint
   (``configuration.pretrained_artifact = dgsr_movielens_32m``), then activate it.

Re-running creates a fresh tenant: that is also how to reset the demo, because
events are permanent (and idempotent) by design.

    python scripts/bootstrap_reel.py --platform-token $PLATFORM_ADMIN_TOKEN
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from graphrec_sdk import STOREFRONT_KEY_SCOPES, GraphRec

HERE = Path(__file__).resolve().parents[1]
ARTIFACT_NAME = "dgsr_movielens_32m"
PRODUCT_CHUNK = 500
EVENT_CHUNK = 200


def step(title: str) -> None:
    print(f"\n== {title}", flush=True)


def env_value(value: object) -> str:
    """Quote values a shell or Compose would split (e.g. the tenant name "Reel 3f2a1c")."""
    text = str(value)
    return f'"{text}"' if any(c in text for c in ' #"\'$`') else text


def write_env(path: Path, updates: dict) -> None:
    updates = {key: env_value(value) for key, value in updates.items()}
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("GRAPHREC_BASE_URL", "http://localhost:8010"))
    parser.add_argument("--platform-token", default=os.environ.get("PLATFORM_ADMIN_TOKEN", ""))
    parser.add_argument("--name", default="Reel")
    parser.add_argument("--env-file", default=str(HERE / ".env"))
    parser.add_argument("--train", action="store_true",
                        help="train DGSR on the tenant's own events instead of importing the MovieLens checkpoint "
                             "(for hosts without model_artifacts/; personas then get a much smaller model)")
    args = parser.parse_args()
    if not args.platform_token:
        raise SystemExit("Pass --platform-token (or set PLATFORM_ADMIN_TOKEN): the 7,951-film catalogue needs a quota override.")

    films = json.loads((HERE / "data" / "films.json").read_text(encoding="utf-8"))
    personas = json.loads((HERE / "data" / "personas.json").read_text(encoding="utf-8"))
    suffix = secrets.token_hex(3)
    email = f"reel-{suffix}@example.org"
    password = "reel-" + secrets.token_urlsafe(18)

    public = GraphRec(base_url=args.base_url, use_env=False)
    step(f"health @ {args.base_url}")
    print(public.health())

    step("register tenant")
    tenant = public.tenant.auth.register(name=f"{args.name} {suffix}", admin_email=email)
    public.tenant.auth.setup_password(setup_token=tenant.setup_token, password=password, email=email)
    admin = public.with_credentials(email=email, password=password)
    print(f"tenant {tenant.id}  admin {email}")

    step("quota override (platform operator)")
    operator = GraphRec(base_url=args.base_url, access_token=args.platform_token, use_env=False)
    operator.platform.tenants.set_quota_override(tenant.id, overrides={"stored_products": 10_000, "training_jobs": 10})

    step("storefront API key")
    key = admin.tenant.api_keys.create(name="reel-storefront", scopes=STOREFRONT_KEY_SCOPES)
    print(f"{key.prefix}... scopes={list(key.scopes)}")

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

    step("train DGSR on the persona histories" if args.train else "import the offline DGSR checkpoint and activate it")
    snapshot = admin.tenant.datasets.create_snapshot(description="Reel persona histories")
    configuration = {"mode": "train", "epochs": 2} if args.train else {"pretrained_artifact": ARTIFACT_NAME}
    job = admin.tenant.training_jobs.create(dataset_snapshot_id=snapshot.id, configuration=configuration)
    job = admin.tenant.training_jobs.wait(job.id, timeout=600, poll_interval=2)
    if job.status != "succeeded" or not job.model_version_id:
        raise SystemExit(f"Import failed: {job.status} {getattr(job, 'failure_reason', '')}")
    version = admin.tenant.model_versions.activate(job.model_version_id)
    print(f"active version {version.id} ({getattr(version, 'version_tag', '')})")

    step("smoke test: one recommendation per persona")
    shop = GraphRec(base_url=args.base_url, api_key=key.secret, use_env=False)
    titles = {f["id"]: f["title"] for f in films}
    for p in personas:
        recs = shop.storefront.recommendations.get(user_id=p["user_id"], top_n=5)
        print(f"  {p['name']:<5} {recs.strategy:<13} " + " | ".join(titles.get(i, i) for i in recs.product_ids))

    write_env(Path(args.env_file), {
        "GRAPHREC_BASE_URL": args.base_url,
        "GRAPHREC_API_KEY": key.secret,
        "REEL_TENANT_NAME": f"{args.name} {suffix}",
        "REEL_ADMIN_EMAIL": email,
        "REEL_ADMIN_PASSWORD": password,
        "REEL_TENANT_ID": str(tenant.id),
        "REEL_MODEL_VERSION_ID": str(version.id),
        "REEL_MODEL_VERSION_TAG": str(getattr(version, "version_tag", "") or ""),
        "REEL_MODEL_SOURCE": "trained" if args.train else "checkpoint",
    })
    live = HERE / "state" / "live_events.jsonl"
    if live.is_file():
        live.unlink()  # live events belonged to the previous tenant
    step(f"done - wrote {args.env_file}. Start: uvicorn app.main:app --port 5290")
    return 0


if __name__ == "__main__":
    sys.exit(main())
