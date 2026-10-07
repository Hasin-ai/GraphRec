"""D-13: the workspace's lifecycle status (``GET /v1/tenant/status``)."""
from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from ..models._base import GraphRecModel
from ._base import AsyncResource, SyncResource

__all__ = ["Account", "AsyncAccount", "TenantStatus"]


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
