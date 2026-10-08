"""Data retention (Phase 5, decision D-21): delete operational rows past their window.

    docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm retention
    python -m scripts.retention --dry-run          # counts only

Runs with the *owner* connection (``RETENTION_DATABASE_URL``, the migration role):
the runtime role ``graphrec_app`` deliberately has no DELETE on these tables, and
RLS is forced for it. Deletes run in batches so no long lock is held.

What is never deleted here: tenants' catalogs, interaction histories, dataset
snapshots, model versions and the append-only audit log. Those belong to the
tenant's lifecycle (tenant deletion), not to a time window.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import create_engine, text

#: (table, condition, description). Windows are in days; see docs/OPERATIONS.md.
RULES: list[tuple[str, str, str]] = [
    ("serving_requests", "occurred_at < now() - interval '90 days'", "per-request serving metrics: 90 days"),
    ("recommendation_feedback", "received_at < now() - interval '180 days'", "feedback: 180 days"),
    ("recommendation_results", "created_at < now() - interval '180 days'", "served lists: 180 days"),
    ("recommendation_records", "created_at < now() - interval '180 days' AND NOT EXISTS "
     "(SELECT 1 FROM recommendation_feedback f WHERE f.tenant_id = recommendation_records.tenant_id "
     "AND f.request_id = recommendation_records.request_id) AND NOT EXISTS "
     "(SELECT 1 FROM recommendation_results r WHERE r.tenant_id = recommendation_records.tenant_id "
     "AND r.request_id = recommendation_records.request_id)",
     "recommendation records: 180 days"),
    ("capacity_events", "occurred_at < now() - interval '90 days'", "capacity decisions: 90 days"),
    ("refresh_sessions", "COALESCE(revoked_at, expires_at) < now() - interval '30 days'", "ended sign-ins: 30 days"),
    ("account_setup_tokens", "COALESCE(used_at, revoked_at, expires_at) < now() - interval '30 days'", "spent setup links: 30 days"),
    ("account_recovery_tokens", "COALESCE(used_at, revoked_at, expires_at) < now() - interval '30 days'", "spent recovery tokens: 30 days"),
    ("registration_requests", "created_at < now() - interval '30 days'", "registration idempotency records: 30 days"),
    ("security_events", "occurred_at < now() - interval '365 days'", "security events: 1 year"),
    # UC-24 reads up to 24 months back; one more month of margin.
    ("usage_events", "occurred_at < date_trunc('month', now()) - interval '25 months'", "usage ledger: 25 months"),
]
BATCH = 5_000


def run(url: str, dry_run: bool) -> dict[str, int]:
    engine = create_engine(url, future=True)
    results: dict[str, int] = {}
    with engine.connect() as connection:
        for table, condition, _ in RULES:
            if dry_run:
                results[table] = connection.execute(text(f"SELECT count(*) FROM {table} WHERE {condition}")).scalar_one()
                continue
            total = 0
            while True:
                with connection.begin():
                    deleted = connection.execute(text(
                        f"DELETE FROM {table} WHERE ctid IN (SELECT ctid FROM {table} WHERE {condition} LIMIT {BATCH})")).rowcount
                total += deleted
                if deleted < BATCH:
                    break
            results[table] = total
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count what would be deleted")
    args = parser.parse_args()
    url = os.environ.get("RETENTION_DATABASE_URL")
    if not url:
        print("Set RETENTION_DATABASE_URL to the owner (migration) connection.", file=sys.stderr)
        return 2
    print(json.dumps({"dry_run": args.dry_run, "deleted" if not args.dry_run else "would_delete": run(url, args.dry_run)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
