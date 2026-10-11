"""D-13: the workspace's lifecycle status (``GET /v1/tenant/status``)."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, cast
from uuid import UUID

from ..models._base import GraphRecModel
from ._base import AsyncResource, SyncResource

__all__ = ["Account", "AsyncAccount", "AsyncTenantAudit", "TenantAudit", "TenantAuditItem", "TenantAuditList", "TenantStatus"]


class TenantStatus(GraphRecModel):
    tenant_id: UUID
    name: str
    #: ``active``, ``suspended``, ``deleting``, ``deleted`` or ``pending``.
    status: str
    message: str
    #: True when the session can only read this status (a suspended workspace).
    restricted_session: bool
    created_at: datetime


class Account(SyncResource):
    def status(self) -> TenantStatus:
        """The workspace's status; the only call a suspended workspace's members may make."""
        return cast(TenantStatus, self._client.request("account.status", cast_to=TenantStatus))


class AsyncAccount(AsyncResource):
    async def status(self) -> TenantStatus:
        return cast(TenantStatus, await self._client.request("account.status", cast_to=TenantStatus))


class TenantAuditItem(GraphRecModel):
    id: UUID
    occurred_at: datetime
    action_type: str
    resource_type: str
    resource_reference: Optional[UUID] = None
    outcome: str
    #: ``tenant_user``, ``api_key``, ``platform_operator`` or ``system``.
    actor_type: str
    #: Set for members and API keys of this tenant; never a platform operator's identity.
    actor_reference: Optional[UUID] = None
    reason: Optional[str] = None
    correlation_id: Optional[UUID] = None


class TenantAuditList(GraphRecModel):
    items: List[TenantAuditItem]
    next_before: Optional[datetime] = None


def _audit_query(action, outcome, since, until, before, limit) -> Dict[str, object]:
    query: Dict[str, object] = {"limit": limit}
    for key, value in (("action", action), ("outcome", outcome), ("since", since), ("until", until), ("before", before)):
        if value is not None:
            query[key] = value.isoformat() if isinstance(value, datetime) else str(value)
    return query


class TenantAudit(SyncResource):
    """UC-31: this tenant's own audit trail (``GET /v1/audit``, scope ``audit:read``)."""

    def list(self, *, action: Optional[str] = None, outcome: Optional[str] = None, since: Optional[datetime] = None,
             until: Optional[datetime] = None, before: Optional[datetime] = None, limit: int = 50) -> TenantAuditList:
        return cast(TenantAuditList, self._client.request(
            "audit.list", query=_audit_query(action, outcome, since, until, before, limit), cast_to=TenantAuditList))


class AsyncTenantAudit(AsyncResource):
    async def list(self, *, action: Optional[str] = None, outcome: Optional[str] = None,
                   since: Optional[datetime] = None, until: Optional[datetime] = None,
                   before: Optional[datetime] = None, limit: int = 50) -> TenantAuditList:
        return cast(TenantAuditList, await self._client.request(
            "audit.list", query=_audit_query(action, outcome, since, until, before, limit), cast_to=TenantAuditList))
