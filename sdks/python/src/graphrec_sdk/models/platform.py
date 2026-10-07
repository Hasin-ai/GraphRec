from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel, ItemList

__all__ = [
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
