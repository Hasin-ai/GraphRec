"""D-13: the tenant's own lifecycle status."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.auth.principal import AuthenticatedPrincipal, authenticated_principal
from graphrec_core.database.models import Tenant
from graphrec_core.database.session import get_db
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.errors import ApiError

router = APIRouter(prefix="/v1/tenant", tags=["account"])

MESSAGES = {
    "active": "This workspace is active.",
    "suspended": "A platform operator suspended this workspace. Its API credentials and integrations are paused, "
                 "and its data is kept. Contact your platform operator to restore access.",
    "deleting": "This workspace is being deleted by a platform operator. Contact your platform operator if this is unexpected.",
}


class TenantStatusResponse(BaseModel):
    tenant_id: UUID
    name: str
    status: Literal["active", "suspended", "deleting", "deleted", "pending"]
    message: str
    #: True when this session can only view the status (D-13).
    restricted_session: bool
    created_at: datetime


@router.get("/status", response_model=TenantStatusResponse)
def get_tenant_status(principal: AuthenticatedPrincipal = Depends(authenticated_principal),
                      db: Session = Depends(get_db)) -> TenantStatusResponse:
    """Any signed-in member may read the workspace status; a member of a suspended
    workspace can read only this (D-13). API keys are not accepted."""
    principal.require_bearer()
    set_local_tenant(db, principal.tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == principal.tenant_id))
    if tenant is None:
        raise ApiError(404, "resource_not_found", "The requested resource was not found")
    return TenantStatusResponse(tenant_id=tenant.id, name=tenant.name, status=tenant.status,
                                message=MESSAGES.get(tenant.status, "Contact your platform operator."),
                                restricted_session=principal.restricted, created_at=tenant.created_at)
