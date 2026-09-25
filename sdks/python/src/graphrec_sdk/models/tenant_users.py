from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from ._base import GraphRecModel, ItemList

__all__ = ["TenantUser", "TenantUserInvitation", "TenantUserList"]


class TenantUser(GraphRecModel):
    id: UUID
    email: str
    display_name: str
    #: ``tenant_administrator`` or ``tenant_developer``.
    role: str
    #: ``invited``, ``active``, ``locked`` or ``disabled``.
    status: str
    created_at: datetime
    last_authenticated_at: Optional[datetime] = None


class TenantUserInvitation(TenantUser):
    #: Returned once by ``POST /v1/tenant/users``; only its hash is stored.
    setup_token: str
    setup_token_expires_at: datetime
    next_step: Optional[str] = None


class TenantUserList(ItemList[TenantUser]):
    total: int = 0
