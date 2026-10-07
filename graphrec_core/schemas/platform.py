from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from graphrec_core.schemas.deployment import RateLimiterStatus


class PlatformTenantResource(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    created_at: datetime


class PlatformTenantListResponse(BaseModel):
    items: list[PlatformTenantResource]


class DeploymentCapacity(BaseModel):
    """XR-F-08: logical serving capacity across tenants (see D-07)."""
    available_tenants: int
    degraded_tenants: int
    desired_capacity: int
    ready_capacity: int


class PlatformPlanResource(BaseModel):
    id: UUID
    code: str
    name: str
    limits: dict[str, int]
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
    #: The acting user, credential or operator, when known.
    actor_reference: UUID | None = None
    action_type: str
    resource_type: str
    resource_reference: UUID | None = None
    outcome: str
    correlation_reference: UUID | None = None
    #: ER-F-11: the reason given for the action, if any.
    reason: str | None = None
    occurred_at: datetime


class PlatformAuditListResponse(BaseModel):
    items: list[PlatformAuditItem]
    #: Pass as ``before`` to read the next (older) page; ``None`` on the last page.
    next_before: datetime | None = None


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


class PlatformStatus(BaseModel):
    status: str
    api_cluster: str
    database: str
    worker_pool: str
    deployments: DeploymentCapacity | None = None
    rate_limiter: RateLimiterStatus
    timestamp: datetime
