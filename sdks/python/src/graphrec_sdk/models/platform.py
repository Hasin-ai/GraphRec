from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import Field

from ._base import GraphRecModel, ItemList

__all__ = [
    "AuditRecord",
    "AuditRecordList",
    "PlatformFailure",
    "PlatformFailureList",
    "PlatformTenant",
    "PlatformTenantList",
    "PricingPlan",
    "PricingPlanList",
    "QuotaOverride",
]


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


class PricingPlanList(ItemList[PricingPlan]):
    pass


class QuotaOverride(GraphRecModel):
    limits: Dict[str, Any] = Field(default_factory=dict)
    overrides: Dict[str, Any] = Field(default_factory=dict)


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
    action_type: str
    resource_type: str
    outcome: str
    occurred_at: datetime


class AuditRecordList(ItemList[AuditRecord]):
    pass
