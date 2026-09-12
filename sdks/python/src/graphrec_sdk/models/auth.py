from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from ._base import GraphRecModel

__all__ = ["AuthTokenPair", "TenantRegistration"]


class AuthTokenPair(GraphRecModel):
    """Tokens issued by ``POST /v1/auth/login`` or ``/v1/auth/setup-password``."""

    access_token: str
    token_type: str = "Bearer"
    #: Access-token lifetime in seconds (15 minutes by default).
    expires_in: int
    refresh_token: str
    #: ``tenant_administrator`` or ``tenant_developer``.
    user_role: str
    scopes: List[str] = []


class TenantRegistration(GraphRecModel):
    """Result of ``POST /v1/tenants``."""

    id: UUID
    name: str
    status: str
    created_at: datetime
    administrator_email: str
    next_step: str
    #: One-time token for :meth:`Authentication.setup_password`. Present only in
    #: the original ``201`` response; an idempotent replay returns ``None``, and
    #: an operator must then issue a new token.
    setup_token: Optional[str] = None
    setup_token_expires_at: Optional[datetime] = None
