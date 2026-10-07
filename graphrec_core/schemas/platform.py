from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PlatformTenantResource(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    created_at: datetime


class PlatformTenantListResponse(BaseModel):
    items: list[PlatformTenantResource]


class PlatformPlanResource(BaseModel):
    id: UUID
    code: str
    name: str
    limits: dict[str, Any]
    is_active: bool
    warnings: list[dict[str, Any]] = []


class PlatformQuotaOverride(BaseModel):
    limits: dict[str, Any]
    overrides: dict[str, Any]
    warnings: list[dict[str, Any]] = []


class PlatformFailureItem(BaseModel):
    id: UUID
    tenant_id: UUID | None = None
    event_type: str
    severity: str
    sanitized_detail: dict[str, Any]
    occurred_at: datetime


class PlatformFailureListResponse(BaseModel):
    items: list[PlatformFailureItem]


class PlatformAuditItem(BaseModel):
    id: UUID
    tenant_id: UUID
    actor_type: str
    action_type: str
    resource_type: str
    outcome: str
    occurred_at: datetime


class PlatformAuditListResponse(BaseModel):
    items: list[PlatformAuditItem]


class PlatformTenantQuota(BaseModel):
    """Effective limits for one tenant: plan base, quota row and overrides combined."""
    plan_id: UUID
    plan_code: str
    overrides: dict[str, Any]
    limits: dict[str, Any]


class PlatformPlanAssignmentResult(PlatformTenantQuota):
    """Result of a plan assignment. ``warnings`` lists acknowledged inventory conflicts."""
    warnings: list[dict[str, Any]] = []


class PlatformRecoveryToken(BaseModel):
    recovery_token: str
    expires_at: datetime


class PlatformRateLimiterStatus(BaseModel):
    backend: str
    status: str
    fail_open_total: int

    model_config = {"extra": "allow"}


class PlatformStatus(BaseModel):
    status: str
    api_cluster: str
    database: str
    worker_pool: str
    deployments: Any | None = None
    rate_limiter: PlatformRateLimiterStatus
    timestamp: datetime
