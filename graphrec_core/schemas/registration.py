from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from graphrec_core.settings import get_settings


class TenantRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    admin_email: EmailStr

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Business name must not be empty")
        if len(normalized) > get_settings().max_tenant_name_length:
            raise ValueError("Business name is too long")
        return normalized

    @field_validator("admin_email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()


class TenantRegistrationResponse(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime
    administrator_email: EmailStr
    next_step: str
    # One-time credential for POST /v1/auth/setup-password. Returned only in the
    # original 201 response; idempotent replays never expose it again.
    setup_token: str | None = None
    setup_token_expires_at: datetime | None = None
