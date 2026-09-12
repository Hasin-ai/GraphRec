"""Seed the demo tenant: catalog, persona histories, snapshot, training, activation.

    python scripts/seed.py                 # uses .env (GRAPHREC_SEED_API_KEY or GRAPHREC_API_KEY)
    python scripts/seed.py --skip-training # catalog and events only

Idempotent: product external IDs are fixed and every seed event ID derives from
``demo-seed-v1 + persona + sequence + product``, so a rerun records duplicates,
not new events. Training on today's backend completes synchronously and is a
placeholder (random item vectors, no offline metrics) - the summary says so.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from _common import env, load_env, require, step

from fixtures.personas import PERSONAS, SEED_HISTORY
from fixtures.products import PRODUCTS
from graphrec_sdk import APIError, AsyncGraphRec, PermissionDeniedError, deterministic_id
from graphrec_sdk.ecommerce import AsyncCatalogSync, AsyncEventTracker

SEED_VERSION = "demo-seed-v1"
HISTORY_START = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


def proof_label(recs, verified_version: str) -> str:
    if recs.fallback_used:
        return "catalog_fallback"
    if verified_version and str(recs.model_version_id) == verified_version:
        return "model_verified"
    return "serving_preview"


async def seed_events(client: AsyncGraphRec) -> dict:
    """Replay each persona's scripted history with deterministic ids and timestamps."""

    async def on_error(error: BaseException, events) -> None:
        raise error  # seeding must fail loudly, never drop events silently

    tracker = AsyncEventTracker(client, batch_size=50, on_error=on_error, default_context={"source": "demo-seed", "seed_version": SEED_VERSION})
    counts = {}
    for offset, (persona_key, history) in enumerate(SEED_HISTORY.items()):
        persona = PERSONAS[persona_key]
        session_id = f"sess_seed_{persona_key}"
        for seq, (event_type, product_id, extra) in enumerate(history, start=1):
            occurred_at = HISTORY_START + timedelta(days=offset, hours=seq * 3)
            event_id = deterministic_id(SEED_VERSION, persona_key, seq, product_id, prefix="seed")
            common = {"session_id": session_id, "occurred_at": occurred_at, "event_id": event_id, "context": {"demo_persona": persona_key, "seed_seq": seq}}
            if event_type == "purchase":
                await tracker.purchase(persona.user_id, product_id, order_id=extra["order_id"], line=extra["line"], price=next(p["price"] for p in PRODUCTS if p["external_id"] == product_id), currency="USD", **common)
            elif event_type == "add_to_cart":
                await tracker.add_to_cart(persona.user_id, product_id, quantity=extra.get("quantity", 1), **common)
            elif event_type == "add_to_wishlist":
                await tracker.add_to_wishlist(persona.user_id, product_id, **common)
            else:
                await tracker.track(event_type, user_id=persona.user_id, product_id=product_id, **common)
        counts[persona_key] = len(history)
    result = await tracker.flush()
    return {"per_persona": counts, "accepted": result.accepted_count if result else 0, "duplicate": result.duplicate_count if result else 0, "rejected": result.rejected_count if result else 0}


async def main(argv=None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=env("GRAPHREC_BASE_URL", "http://localhost:8010"))
    parser.add_argument("--skip-training", action="store_true")
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args(argv)

    api_key = env("GRAPHREC_SEED_API_KEY") or require("GRAPHREC_API_KEY")
    disable_missing = env("DEMO_DISABLE_MISSING", "false").lower() == "true"
    verified_version = env("MODEL_PROOF_VERSION_ID") if env("MODEL_PROOF_VERIFIED", "false").lower() == "true" else ""
    summary: dict = {}

    async with AsyncGraphRec(base_url=args.base_url, api_key=api_key, use_env=False) as client:
        step("1. health")
        print(await client.health())

        step("2. catalog sync")
        if disable_missing:
            print("WARNING: DEMO_DISABLE_MISSING=true - tenant products missing from the demo feed will be disabled.")
        report = await AsyncCatalogSync(client).run(PRODUCTS, disable_missing=disable_missing, idempotency_key=f"{SEED_VERSION}-catalog")
        print(report.summary())
        if not report.ok:
            for failure in report.upsert.failures:
                print(f"  rejected {failure.external_id}: {failure.reason}")
            raise SystemExit("Catalog sync reported failures; fix the fixtures before seeding events.")
        summary["products"] = report.upsert.accepted_count

        step("3. persona histories")
        try:
            events = await seed_events(client)
        except APIError as error:
            partial = getattr(error, "partial_result", None)
            raise SystemExit(f"Event seeding failed (correlation id {error.correlation_id}); partial result: {partial}") from error
        print(f"events accepted={events['accepted']} duplicate={events['duplicate']} rejected={events['rejected']} per persona={events['per_persona']}")
        summary["events"] = events

        if args.skip_training:
            print("\n--skip-training: leaving snapshot/training/activation alone.")
        else:
            step("4. dataset snapshot")
            try:
                snapshot = await client.datasets.create_snapshot(description=f"{SEED_VERSION} {datetime.now(timezone.utc):%Y-%m-%d %H:%M}")
            except PermissionDeniedError as error:
                raise SystemExit(
                    "The key lacks training scopes. Set GRAPHREC_SEED_API_KEY to a key with training:write, models:write and models:deploy "
                    f"(scripts/bootstrap_tenant.py creates one). Correlation id {error.correlation_id}."
                ) from error
            print(f"snapshot {snapshot.id}: {snapshot.event_count} events, {snapshot.product_count} products, {snapshot.user_count} users")
            summary["snapshot"] = str(snapshot.id)

            step("5. training job (placeholder training: synchronous, random item vectors, no offline metrics)")
            job = await client.training_jobs.create(dataset_snapshot_id=snapshot.id, configuration={"seed": SEED_VERSION})
            job = await client.training_jobs.wait(job.id, timeout=300, poll_interval=2)
            print(f"job {job.id}: {job.status}; model version {job.model_version_id}")
            if job.status != "succeeded" or not job.model_version_id:
                raise SystemExit(f"Training did not succeed: {job.failure_reason}")
            summary["job"] = str(job.id)

            step("6. activate model version")
            version = await client.model_versions.activate(job.model_version_id)
            print(f"version {version.version_tag} ({version.id}) is {version.status}; metrics={version.metrics or 'none reported'}")
            summary["model_version"] = str(version.id)

        step("7. recommendations per persona")
        statuses = set()
        for key, persona in PERSONAS.items():
            if persona.user_id:
                recs = await client.recommendations.get(user_id=persona.user_id, top_n=args.top_n)
            else:
                recs = await client.recommendations.for_session("sess_seed_check", top_n=args.top_n)
            label = proof_label(recs, verified_version)
            statuses.add(label)
            print(f"  {persona.name:<12} {label:<16} strategy={recs.strategy:<17} version={recs.model_version_id} -> {recs.product_ids}")
        summary["proof_status"] = sorted(statuses)

    step("summary")
    for key, value in summary.items():
        print(f"  {key:<14} {value}")
    print(
        "\nProof status is 'serving_preview' unless MODEL_PROOF_VERIFIED=true names this exact version after\n"
        "scripts/verify_personalization.py has passed. Today's training is a placeholder, so expect identical\n"
        "rankings for every persona in the compare lab - that is the honest current state."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
