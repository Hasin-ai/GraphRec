from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ApiKeyScope = Literal[
    "billing:read",
    "usage:read",
    "catalog:read",
    "catalog:write",
    "events:read",
    "events:write",
    "training:read",
    "training:write",
    "models:read",
    "models:write",
    "models:deploy",
    "recommendations:read",
    "deployments:read",
    "metrics:read",
]


class ApiKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    scopes: list[ApiKeyScope] = Field(min_length=1, max_length=12)
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank")
        return normalized

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value: list[ApiKeyScope]) -> list[ApiKeyScope]:
        if len(value) != len(set(value)):
            raise ValueError("Scopes must be unique")
        return value


class ApiKeyRotateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grace_period_seconds: int = Field(ge=0, le=86_400)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Reason must not be blank")
        return normalized


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    prefix: str
    scopes: list[ApiKeyScope]
    status: Literal["active", "expired", "revoked"]
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    grace_expires_at: datetime | None


class ApiKeySecretResponse(ApiKeyResponse):
    secret: str


class ApiKeyListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ApiKeyResponse]
