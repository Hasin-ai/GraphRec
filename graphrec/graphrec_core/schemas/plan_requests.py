"""Plan change requests (migration 0039)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

PlanCode = Literal["free", "basic", "pro"]
RequestStatus = Literal["pending", "approved", "rejected", "cancelled"]


class PlanChangeRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The plan to move to: ``free`` (Free demo), ``basic`` or ``pro``.
    plan_code: PlanCode
    #: Optional note for the operator (what the workspace needs the capacity for).
    message: str | None = Field(default=None, max_length=500)

    @field_validator("message")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class PlanChangeRequestResource(BaseModel):
    """A request as the tenant sees it."""

    id: UUID
    status: RequestStatus
    current_plan_code: str
    current_plan_name: str
    requested_plan_code: str
    requested_plan_name: str
    message: str | None = None
    decision_reason: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class PlanChangeRequestList(BaseModel):
    items: list[PlanChangeRequestResource]
    #: The open request, if any (also the first item).
    pending: PlanChangeRequestResource | None = None


class PlatformPlanChangeRequest(PlanChangeRequestResource):
    """A request as a platform operator sees it."""

    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    requested_plan_id: UUID
    #: The tenant's plan right now (differs from ``current_plan_code`` if it changed since the request).
    active_plan_code: str | None = None
    requested_by: str | None = None
    decided_by: UUID | None = None
    decided_by_email: str | None = None


class PlatformPlanChangeRequestList(BaseModel):
    items: list[PlatformPlanChangeRequest]
    pending_count: int


class PlanRequestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Why the operator decided this way; shown to the tenant and written to the audit trail.
    reason: str = Field(..., min_length=3, max_length=500)
    #: Approve even if the new plan's limits are below what the tenant already stores.
    acknowledge_below_usage: bool = False


class PlanRequestDecisionResult(BaseModel):
    request: PlatformPlanChangeRequest
    #: Inventory limits the approved plan puts the tenant over (acknowledged).
    warnings: list[dict] = Field(default_factory=list)
