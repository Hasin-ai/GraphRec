from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel, ItemList

__all__ = [
    "PlanRequestDecision",
    "PlatformPlanRequest",
    "PlatformPlanRequestList",
    "AuditRecord",
    "AuditRecordList",
    "LimitConflict",
    "PlatformFailure",
    "PlatformFailureList",
    "PlatformStatus",
    "PlatformTenant",
    "PlatformTenantList",
    "PricingPlan",
    "PricingPlanList",
    "QuotaOverride",
    "RecoveryToken",
    "TenantQuota",
]


class LimitConflict(GraphRecModel):
    """An inventory limit that a tenant already exceeds after a limit change.

    Returned in ``warnings`` when the change was applied with
    ``acknowledge_below_usage=True``, and in the error details of a refused change.
    """

    limit_name: str
    limit: int
    used: int
    over_by: int
    #: Set for plan updates, which can affect several tenants.
    tenant_id: Optional[UUID] = None
    tenant_name: Optional[str] = None


class PlatformTenant(GraphRecModel):
    id: UUID
    slug: str
    name: str
    status: str
    created_at: datetime


class PlatformTenantList(ItemList[PlatformTenant]):
    pass


class PricingPlan(GraphRecModel):
    id: UUID
    code: str
    name: str
    limits: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    #: Tenants left above an inventory limit by an acknowledged update.
    warnings: List[LimitConflict] = Field(default_factory=list)


class PricingPlanList(ItemList[PricingPlan]):
    pass


class QuotaOverride(GraphRecModel):
    limits: Dict[str, Any] = Field(default_factory=dict)
    overrides: Dict[str, Any] = Field(default_factory=dict)
    #: Inventory limits the tenant exceeds after an acknowledged change.
    warnings: List[LimitConflict] = Field(default_factory=list)


class TenantQuota(QuotaOverride):
    plan_id: UUID
    plan_code: str


class PlatformFailure(GraphRecModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    event_type: str
    severity: str
    sanitized_detail: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class PlatformFailureList(ItemList[PlatformFailure]):
    pass


class AuditRecord(GraphRecModel):
    id: UUID
    tenant_id: UUID
    actor_type: str
    actor_reference: Optional[UUID] = None
    action_type: str
    resource_type: str
    resource_reference: Optional[UUID] = None
    outcome: str
    correlation_reference: Optional[UUID] = None
    #: The reason given for the action, if any (ER-F-11).
    reason: Optional[str] = None
    occurred_at: datetime


class AuditRecordList(ItemList[AuditRecord]):
    #: Cursor for the next (older) page; pass to ``list_audit_logs(before=...)``.
    next_before: Optional[datetime] = None


class RecoveryToken(GraphRecModel):
    """One-time account-recovery proof issued by an operator."""

    recovery_token: str
    expires_at: datetime


class PlatformStatus(GraphRecModel):
    """Shared service health (``GET /v1/platform/status``)."""

    #: ``healthy`` or ``degraded``.
    status: str
    api_cluster: str
    database: str
    worker_pool: str
    deployments: Optional[Any] = None
    rate_limiter: Optional[Dict[str, Any]] = None
    timestamp: datetime


class PlatformUsageDimension(GraphRecModel):
    type: str
    used: float
    limit: Optional[int] = None
    measured: bool = True


class PlatformTenantUsage(GraphRecModel):
    tenant_id: UUID
    name: str
    status: str
    plan_code: Optional[str] = None
    period_start: Optional[datetime] = None
    dimensions: List[PlatformUsageDimension] = []
    #: True when this tenant's usage could not be read (never reported as zero).
    unavailable: bool = False


class PlatformUsageList(GraphRecModel):
    items: List[PlatformTenantUsage]


class PlatformPlanRequest(GraphRecModel):
    """A tenant's plan change request as an operator sees it."""

    id: UUID
    status: str
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    current_plan_code: str
    current_plan_name: str
    requested_plan_id: UUID
    requested_plan_code: str
    requested_plan_name: str
    #: The tenant's plan right now.
    active_plan_code: Optional[str] = None
    message: Optional[str] = None
    requested_by: Optional[str] = None
    decision_reason: Optional[str] = None
    decided_by: Optional[UUID] = None
    decided_by_email: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None


class PlatformPlanRequestList(GraphRecModel):
    items: List[PlatformPlanRequest] = Field(default_factory=list)
    pending_count: int = 0


class PlanRequestDecision(GraphRecModel):
    request: PlatformPlanRequest
    #: Inventory limits the approved plan puts the tenant over (acknowledged).
    warnings: List[LimitConflict] = Field(default_factory=list)
