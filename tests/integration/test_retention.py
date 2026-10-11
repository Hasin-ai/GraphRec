"""Phase 5 retention rules (D-21): old operational rows go, recent ones and tenant data stay."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from graphrec_core.auth.audit import protected_auth_hash
from graphrec_core.database.models import AuditLog, UsageEvent
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from scripts.retention import run
from tests.integration.test_srs_acceptance import provision

pytestmark = pytest.mark.integration
OWNER_URL = os.environ.get("RETENTION_DATABASE_URL", "postgresql+psycopg://graphrec_owner:local@localhost:5432/graphrec")


def test_retention_deletes_only_rows_past_their_window(client):
    tenant, headers = provision(client)
    tid, now = UUID(tenant), datetime.now(timezone.utc)
    old_usage, kept_usage, old_event = f"old-{uuid4()}", f"kept-{uuid4()}", uuid4()
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tid)
        db.add_all([
            UsageEvent(id=uuid4(), tenant_id=tid, usage_type="accepted_events", quantity=Decimal(1), source_id="t",
                       idempotency_key=old_usage, occurred_at=now - timedelta(days=31 * 27)),
            UsageEvent(id=uuid4(), tenant_id=tid, usage_type="accepted_events", quantity=Decimal(1), source_id="t",
                       idempotency_key=kept_usage, occurred_at=now - timedelta(days=31 * 20)),
        ])
        db.execute(text("INSERT INTO security_events (id, tenant_id, event_type, severity, source_hash, sanitized_detail, occurred_at) "
                        "VALUES (:id, :tenant, 'retention_test', 'info', :source, '{}'::jsonb, :at)"),
                   {"id": old_event, "tenant": tid, "source": protected_auth_hash("t"), "at": now - timedelta(days=400)})
    audits_before = _audits(tid)
    assert run(OWNER_URL, dry_run=True)["usage_events"] >= 1
    deleted = run(OWNER_URL, dry_run=False)
    assert deleted["usage_events"] >= 1 and deleted["security_events"] >= 1
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tid)
        keys = set(db.scalars(select(UsageEvent.idempotency_key).where(UsageEvent.tenant_id == tid)))
    assert old_usage not in keys and kept_usage in keys     # 25-month window keeps UC-24's 24 months
    assert _audits(tid) == audits_before                     # the audit log is never trimmed
    assert run(OWNER_URL, dry_run=True)["usage_events"] == 0


def _audits(tid):
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tid)
        return db.scalar(select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tid))
