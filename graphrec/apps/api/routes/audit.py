"""UC-31 / ER-F-11 (tenant side): a tenant's own audit trail, redacted.

Only the fields a tenant administrator needs are returned: what happened, to
what, the outcome, who acted (members of this tenant by id; API keys by id;
platform operators only as "platform operator"), the reason given, and the
correlation id. Internal detail stays in the platform view.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.models import AuditLog
from graphrec_core.database.session import get_db
from graphrec_core.database.tenancy import set_local_tenant

router = APIRouter(prefix="/v1", tags=["audit"])
TENANT_ACTORS = {"tenant_user", "api_key"}


class TenantAuditItem(BaseModel):
    id: UUID
    occurred_at: datetime
    action_type: str
    resource_type: str
    resource_reference: UUID | None = None
    outcome: str
    #: ``tenant_user``, ``api_key``, ``platform_operator`` or ``system``.
    actor_type: str
    #: A member or API key of this tenant; never a platform operator's identity.
    actor_reference: UUID | None = None
    reason: str | None = None
    correlation_id: UUID | None = None


class TenantAuditList(BaseModel):
    items: list[TenantAuditItem]
    next_before: datetime | None = None


@router.get("/audit", response_model=TenantAuditList)
def list_tenant_audit(
    action: str | None = Query(default=None, max_length=100),
    outcome: str | None = Query(default=None, max_length=20),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    before: datetime | None = Query(default=None, description="Keyset cursor from next_before."),
    limit: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(authenticated_principal),
    db: Session = Depends(get_db),
) -> TenantAuditList:
    principal.require_bearer()
    principal.require_scope("audit:read")
    set_local_tenant(db, principal.tenant_id)
    query = select(AuditLog).where(AuditLog.tenant_id == principal.tenant_id)
    for column, value in ((AuditLog.action_type, action), (AuditLog.outcome, outcome)):
        if value:
            query = query.where(column == value)
    if since:
        query = query.where(AuditLog.occurred_at >= since)
    if until:
        query = query.where(AuditLog.occurred_at < until)
    if before:
        query = query.where(AuditLog.occurred_at < before)
    rows = db.scalars(query.order_by(AuditLog.occurred_at.desc()).limit(limit + 1)).all()
    items = [TenantAuditItem(
        id=row.id, occurred_at=row.occurred_at, action_type=row.action_type, resource_type=row.resource_type,
        resource_reference=row.resource_reference, outcome=row.outcome,
        actor_type="platform_operator" if row.actor_type == "platform_administrator" else row.actor_type,
        actor_reference=row.actor_reference if row.actor_type in TENANT_ACTORS else None,
        reason=(row.redacted_details or {}).get("justification"), correlation_id=row.correlation_reference,
    ) for row in rows[:limit]]
    return TenantAuditList(items=items, next_before=items[-1].occurred_at if len(rows) > limit else None)
