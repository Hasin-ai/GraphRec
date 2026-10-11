from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def set_local_tenant(session: Session, tenant_id: UUID) -> None:
    if not session.in_transaction():
        session.begin()
    session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def set_audit_reason(session: Session, reason: str | None) -> None:
    """A-09: attach ``reason`` to every audit row written in this transaction
    (migration 0034 trigger). Blank or missing reasons attach nothing."""
    if not reason or not reason.strip():
        return
    if not session.in_transaction():
        session.begin()
    session.execute(text("SELECT set_config('app.audit_reason', :reason, true)"), {"reason": reason.strip()[:500]})
