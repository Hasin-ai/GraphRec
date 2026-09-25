from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

TenantUserRole = Literal["tenant_administrator", "tenant_developer"]


class TenantUserInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    role: TenantUserRole = "tenant_developer"
    display_name: str | None = Field(default=None, min_length=1, max_length=120)


class TenantUserResource(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    role: str
    status: str
    created_at: datetime
    last_authenticated_at: datetime | None = None


class TenantUserInviteResponse(TenantUserResource):
    #: Returned once; only its hash is stored (same contract as registration).
    setup_token: str
    setup_token_expires_at: datetime
    next_step: str = "POST /v1/auth/setup-password with this setup_token"


class TenantUserListResponse(BaseModel):
    items: list[TenantUserResource]
    total: int
