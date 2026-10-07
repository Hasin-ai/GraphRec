from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from pydantic import EmailStr
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from graphrec_core.auth.platform import platform_administrator
from graphrec_core.auth.service import AuthenticationService
from graphrec_core.database.models import PricingPlan
from graphrec_core.database.session import get_db
from graphrec_core.database.tenancy import set_audit_reason
from graphrec_core.errors import ApiError
from graphrec_core.subscription.service import SubscriptionService
from graphrec_core.usage.limits import limits_below_inventory
from graphrec_core.usage.service import UsageService
from graphrec_core.schemas.usage import UsageSummaryResponse
from graphrec_core.settings import Settings, get_settings
from graphrec_core.schemas.platform import (
    PlatformAuditItem,
    PlatformAuditListResponse,
    PlatformFailureItem,
    PlatformFailureListResponse,
    PlatformPlanAssignmentResult,
    PlatformPlanResource,
    PlatformQuotaOverride,
    PlatformRecoveryToken,
    PlatformStatus,
    PlatformTenantQuota,
    PlatformTenantListResponse,
    PlatformTenantResource,
)

router = APIRouter(
    prefix="/v1/platform",
    tags=["platform"],
    dependencies=[Depends(platform_administrator)],
)

TENANT_STATUSES = frozenset({"active", "suspended", "deleting", "deleted"})
RECENT_LIMIT = 50


Reason = Annotated[str, Field(min_length=3, max_length=500)]


class TenantStatusUpdate(BaseModel):
    status: str = Field(..., max_length=20)
    #: UC-27 / ER-F-11: why the operator changed the tenant's status (stored in the audit trail).
    reason: Reason


class QuotaOverrideUpdate(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)
    # Lowering an inventory limit below current usage is refused unless the
    # operator confirms it; nothing is deleted, but further growth is blocked.
    acknowledge_below_usage: bool = False
    reason: Reason | None = None


class PlanAssignment(BaseModel):
    plan_id: UUID
    acknowledge_below_usage: bool = False
    reason: Reason | None = None


class PlanUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    limits: dict[str, Annotated[int, Field(strict=True, ge=0, le=9_000_000_000_000_000)]]
    is_active: bool
    acknowledge_below_usage: bool = False
    reason: Reason | None = None


def _guard_below_usage(db: Session, conflicts: list[dict[str, Any]], acknowledged: bool) -> list[dict[str, Any]]:
    """Refuse (and roll back) a limit change that puts tenants over an inventory
    limit, unless the operator acknowledged it; return the conflicts as warnings."""
    if conflicts and not acknowledged:
        db.rollback()
        raise ApiError(409, "limit_below_usage",
            "The new limits are below what the tenant already stores. Existing data is kept, but the tenant "
            "cannot add more until usage drops. Resend with acknowledge_below_usage=true to apply anyway.",
            details={"conflicts": conflicts})
    return conflicts


class RecoveryIssue(BaseModel):
    email: EmailStr
    reason: Reason | None = None


@router.get("/tenants/{tenant_id}/quotas", response_model=PlatformTenantQuota)
def get_tenant_quota(tenant_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    config = db.scalar(text("SELECT public.platform_tenant_plan(:tenant_id)"), {"tenant_id": tenant_id})
    if config is None:
        raise _tenant_not_found(tenant_id)
    return {"plan_id": config['plan_id'], "plan_code": config['plan_code'], "overrides": config['overrides'],
        "limits": SubscriptionService._effective_limits(config['plan_limits'], config['quota_limits'], config['overrides'])}


@router.get("/tenants/{tenant_id}/usage", response_model=UsageSummaryResponse)
def get_tenant_usage(tenant_id: UUID, request: Request, db: Session = Depends(get_db)) -> UsageSummaryResponse:
    # Existence check uses the platform-only SQL function before selecting a
    # tenant RLS context. No customer or event payload leaves this endpoint.
    get_tenant_quota(tenant_id, db)
    return UsageService(db).get_for_platform(tenant_id, correlation_id=request.state.correlation_id)


@router.post("/tenants/{tenant_id}/recovery", response_model=PlatformRecoveryToken)
def issue_account_recovery(tenant_id: UUID, payload: RecoveryIssue, request: Request,
                           db: Session = Depends(get_db),
                           app_settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    tenant = get_platform_tenant(tenant_id, db)
    if tenant.status != "active":
        raise ApiError(409, "tenant_inactive", "Tenant is not active.")
    set_audit_reason(db, payload.reason)
    token, expires_at = AuthenticationService(db, app_settings).issue_recovery_token(
        tenant_id=tenant_id, email=str(payload.email).lower(), correlation_id=request.state.correlation_id,
    )
    return {"recovery_token": token, "expires_at": expires_at}


@router.post("/tenants/{tenant_id}/plan", response_model=PlatformPlanAssignmentResult)
def assign_tenant_plan(tenant_id: UUID, payload: PlanAssignment, request: Request, db: Session = Depends(get_db)):
    set_audit_reason(db, payload.reason)
    changed = db.scalar(text("SELECT public.platform_assign_plan(:tenant_id, :plan_id, :correlation_id)"),
        {"tenant_id": tenant_id, "plan_id": payload.plan_id, "correlation_id": request.state.correlation_id})
    if not changed:
        raise ApiError(404, "resource_not_found", "Tenant or active plan not found.")
    # Evaluate inside the same transaction, so a refused change is rolled back.
    effective = get_tenant_quota(tenant_id, db)
    warnings = _guard_below_usage(db, limits_below_inventory(db, tenant_id, effective["limits"]), payload.acknowledge_below_usage)
    db.commit()
    return {**effective, "warnings": warnings}


def _tenant_not_found(tenant_id: UUID) -> ApiError:
    return ApiError(404, "resource_not_found", f"Tenant '{tenant_id}' not found.")


@router.get("/tenants", response_model=PlatformTenantListResponse)
def list_platform_tenants(db: Session = Depends(get_db)) -> PlatformTenantListResponse:
    rows = db.execute(text("SELECT * FROM public.platform_list_tenants()")).mappings().all()
    return PlatformTenantListResponse(items=[PlatformTenantResource(**row) for row in rows])


@router.get("/tenants/{tenant_id}", response_model=PlatformTenantResource)
def get_platform_tenant(tenant_id: UUID, db: Session = Depends(get_db)) -> PlatformTenantResource:
    row = (
        db.execute(
            text("SELECT * FROM public.platform_list_tenants() WHERE id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _tenant_not_found(tenant_id)
    return PlatformTenantResource(**row)


@router.post("/tenants/{tenant_id}/status", response_model=PlatformTenantResource)
def update_platform_tenant_status(
    tenant_id: UUID,
    payload: TenantStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> PlatformTenantResource:
    if payload.status not in TENANT_STATUSES:
        raise ApiError(
            422,
            "validation_failed",
            "Unsupported tenant status",
            details={"fields": [{"field": "status", "message": f"Must be one of {sorted(TENANT_STATUSES)}"}]},
        )
    set_audit_reason(db, payload.reason)
    row = (
        db.execute(
            text(
                "SELECT * FROM public.platform_set_tenant_status"
                "(:tenant_id, :status, :correlation_id)"
            ),
            {
                "tenant_id": tenant_id,
                "status": payload.status,
                "correlation_id": request.state.correlation_id,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        db.rollback()
        raise _tenant_not_found(tenant_id)
    db.commit()
    return PlatformTenantResource(**row)


@router.get("/plans", response_model=list[PlatformPlanResource])
def list_platform_plans(db: Session = Depends(get_db)) -> list[PlatformPlanResource]:
    plans = db.execute(select(PricingPlan).order_by(PricingPlan.code)).scalars().all()
    return [
        PlatformPlanResource(id=p.id, code=p.code, name=p.name, limits=p.limits, is_active=p.is_active)
        for p in plans
    ]


@router.put("/plans/{plan_id}", response_model=PlatformPlanResource)
def update_platform_plan(plan_id: UUID, payload: PlanUpdate, request: Request,
                         db: Session = Depends(get_db)) -> PlatformPlanResource:
    plan = db.scalar(select(PricingPlan).where(PricingPlan.id == plan_id))
    if plan is None:
        raise ApiError(404, "resource_not_found", "Plan not found.")
    if not payload.name.strip() or set(payload.limits) != set(plan.limits):
        raise ApiError(422, "validation_failed", "Provide a name and every supported plan limit exactly once.")
    set_audit_reason(db, payload.reason)
    row = db.execute(text("SELECT * FROM public.platform_update_plan"
        "(:plan_id, :name, CAST(:limits AS jsonb), :active, :correlation_id)"), {
        "plan_id": plan_id, "name": payload.name.strip(), "limits": json.dumps(payload.limits),
        "active": payload.is_active, "correlation_id": request.state.correlation_id,
    }).mappings().one_or_none()
    if row is None:
        db.rollback()
        raise ApiError(404, "resource_not_found", "Plan not found.")
    conflicts: list[dict[str, Any]] = []
    # Subscriptions are RLS-protected, so walk tenants through the platform-only functions.
    for tenant in db.execute(text("SELECT * FROM public.platform_list_tenants()")).mappings().all():
        if tenant["status"] == "deleted":
            continue
        quota = get_tenant_quota(tenant["id"], db)
        if str(quota["plan_id"]) != str(plan_id):
            continue
        conflicts += [{"tenant_id": str(tenant["id"]), "tenant_name": tenant["name"], **c}
                      for c in limits_below_inventory(db, tenant["id"], quota["limits"])]
    warnings = _guard_below_usage(db, conflicts, payload.acknowledge_below_usage)
    db.commit()
    return PlatformPlanResource(**row, warnings=warnings)


@router.post("/tenants/{tenant_id}/quotas", response_model=PlatformQuotaOverride)
def set_tenant_quota_override(
    tenant_id: UUID,
    payload: QuotaOverrideUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> PlatformQuotaOverride:
    current = get_tenant_quota(tenant_id, db)
    if any(key not in current['limits'] or isinstance(value, bool) or not isinstance(value, int) or value < 0
           for key, value in payload.overrides.items()):
        raise ApiError(422, "validation_failed", "Overrides must name supported limits and contain non-negative integers.")
    set_audit_reason(db, payload.reason)
    row = (
        db.execute(
            text(
                "SELECT * FROM public.platform_set_quota_overrides"
                "(:tenant_id, CAST(:overrides AS jsonb), :correlation_id)"
            ),
            {
                "tenant_id": tenant_id,
                "overrides": json.dumps(payload.overrides),
                "correlation_id": request.state.correlation_id,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        db.rollback()
        raise _tenant_not_found(tenant_id)
    # row["limits"] are the base limits; overrides apply on top, so check the effective ones.
    effective = get_tenant_quota(tenant_id, db)["limits"]
    warnings = _guard_below_usage(db, limits_below_inventory(db, tenant_id, effective), payload.acknowledge_below_usage)
    db.commit()
    return PlatformQuotaOverride(limits=row["limits"], overrides=row["overrides"], warnings=warnings)


@router.get("/failures", response_model=PlatformFailureListResponse)
def list_platform_failures(db: Session = Depends(get_db)) -> PlatformFailureListResponse:
    rows = (
        db.execute(
            text("SELECT * FROM public.platform_recent_security_events(:limit)"),
            {"limit": RECENT_LIMIT},
        )
        .mappings()
        .all()
    )
    return PlatformFailureListResponse(items=[PlatformFailureItem(**row) for row in rows])


@router.get("/audit", response_model=PlatformAuditListResponse)
def list_platform_audit_logs(
    tenant_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None, max_length=100),
    outcome: str | None = Query(default=None, max_length=20),
    since: datetime | None = Query(default=None, description="Inclusive ISO-8601 start."),
    until: datetime | None = Query(default=None, description="Exclusive ISO-8601 end."),
    before: datetime | None = Query(default=None, description="Keyset cursor from next_before."),
    limit: int = Query(default=RECENT_LIMIT, ge=1, le=500),
    db: Session = Depends(get_db),
) -> PlatformAuditListResponse:
    """UC-31: the immutable action history, newest first, filtered and paginated."""
    rows = db.execute(
        text("SELECT * FROM public.platform_audit_search(:tenant, :action, :outcome, :since, :until, :before, :limit)"),
        {"tenant": tenant_id, "action": action, "outcome": outcome, "since": since, "until": until,
         "before": before, "limit": limit + 1},
    ).mappings().all()
    items = [PlatformAuditItem(**row) for row in rows[:limit]]
    return PlatformAuditListResponse(items=items, next_before=items[-1].occurred_at if len(rows) > limit else None)


@router.get("/status", response_model=PlatformStatus)
def get_platform_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    worker = "unavailable"
    deployments = None
    try:
        db.execute(text("SELECT 1"))
        database = "connected"
        worker = "online" if db.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND classid = 0 AND objid = 714629381 AND granted)")) else "unavailable"
        deployments = db.scalar(text("SELECT public.platform_deployment_capacity()"))
    except SQLAlchemyError:
        db.rollback()
        database = "unavailable"
    from graphrec_core.usage.admission import get_admission
    limiter = get_admission().status()
    return {
        "status": "healthy" if database == "connected" and limiter["status"] != "degraded" else "degraded",
        "api_cluster": "online",
        "database": database,
        "worker_pool": worker,
        "deployments": deployments,
        "rate_limiter": limiter,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class PlatformUsageDimension(BaseModel):
    type: str
    used: float
    limit: int | None = None
    measured: bool = True


class PlatformTenantUsage(BaseModel):
    tenant_id: UUID
    name: str
    status: str
    plan_code: str | None = None
    period_start: datetime | None = None
    dimensions: list[PlatformUsageDimension] = []
    #: True when this tenant's usage could not be read (shown as unavailable, never as zero).
    unavailable: bool = False


class PlatformUsageList(BaseModel):
    items: list[PlatformTenantUsage]


@router.get("/usage", response_model=PlatformUsageList)
def list_platform_usage(request: Request, db: Session = Depends(get_db)) -> PlatformUsageList:
    """UC-29: every tenant's usage against its limits for the current period.
    Aggregates only; no customer or event payloads leave this endpoint."""
    items: list[PlatformTenantUsage] = []
    for tenant in db.execute(text("SELECT * FROM public.platform_list_tenants()")).mappings().all():
        if tenant["status"] == "deleted":
            continue
        try:
            plan = db.scalar(text("SELECT public.platform_tenant_plan(:id)"), {"id": tenant["id"]})
            summary = UsageService(db).get_for_platform(tenant["id"], correlation_id=request.state.correlation_id)
            items.append(PlatformTenantUsage(
                tenant_id=tenant["id"], name=tenant["name"], status=tenant["status"],
                plan_code=plan["plan_code"] if plan else None, period_start=summary.period_start,
                dimensions=[PlatformUsageDimension(type=d.type, used=d.used, limit=d.limit, measured=d.measured)
                            for d in summary.dimensions]))
        except ApiError:
            db.rollback()
            items.append(PlatformTenantUsage(tenant_id=tenant["id"], name=tenant["name"], status=tenant["status"],
                                             unavailable=True))
    return PlatformUsageList(items=items)
