"""QA fixture: seed products with backdated creation times for XR-F-04 freshness checks.

Usage (inside the api container):
    python -m scripts.seed_aged_products <tenant_id> [count] [step_days]

Creates `count` products (default 30) whose created_at spans
0 .. (count-1)*step_days days ago (default step 2 days, i.e. ~2 months).
External ids are zero-padded so that id order == oldest first, which makes the
fallback ranking (equal popularity, tie-break by external id) prefer OLD items
when no rules apply. Test-only; it writes through the normal RLS tenant context.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from graphrec_core.database.models import Product
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant


def main(argv: list[str]) -> None:
    tenant_id = UUID(argv[1])
    count = int(argv[2]) if len(argv) > 2 else 30
    step = int(argv[3]) if len(argv) > 3 else 2
    now = datetime.now(timezone.utc)
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tenant_id)
        for i in range(count):
            age = (count - 1 - i) * step          # f00 is the oldest
            created = now - timedelta(days=age)
            db.add(Product(id=uuid4(), tenant_id=tenant_id, external_id=f"f{i:02d}", title=f"Aged item {i:02d} ({age}d)",
                           price=Decimal("10.00"), category=None, is_active=True, availability_status="available",
                           metadata_json={"qa_age_days": age}, created_at=created, updated_at=created))
    print(f"seeded {count} products aged 0..{(count - 1) * step} days for tenant {tenant_id}")


if __name__ == "__main__":
    main(sys.argv)
