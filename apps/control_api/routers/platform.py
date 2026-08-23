"""The 13 platform-realm endpoints, under `/v1/platform/*` (D6).

Three things about this file are unlike every other router, and all three follow
from the realm rather than from any of the individual routes.

**Every route names its permission.** There is no default and no blanket
"platform administrator" dependency: `require_permission` is applied route by
route, and applying it beside the route rather than in one table at the bottom
is deliberate — a guard declared somewhere other than the route it guards is a
guard nobody reviews when the route changes.

**`app.tenant_id` is never set.** The session on the principal connects as
`graphrec_platform`, which holds grants on the twelve tables `/admin/*` renders
and on nothing else. A handler here that tried to read a tenant's products would
fail on a missing privilege, not on an empty result, and that is the difference
between a boundary and a convention.

**One route returns `200` with parts of itself refused.** `GET /tenants/{id}`
composes three permissions and marks the sections the caller cannot see. It is
the only place in this system where an authorization decision is data rather
than a status code, and §12.10 argues the alternative: three calls, and a client
guessing which `403`s are fatal.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from apps.control_api.deps import (
    PlatformAudit,
    PlatformPrincipal,
    get_settings_dep,
    require_permission,
)
from apps.control_api.schemas import (
    AssignedTenantBody,
    AssignPlanRequest,
    ChangeTenantStatusRequest,
    CreatePlanRequest,
    FailureListResponse,
    FailureRowBody,
    FailureSummaryBody,
    GrantOverrideRequest,
    MeasurementGapBody,
    PlanBody,
    PlanDetailResponse,
    PlanListResponse,
    PlatformAuditListResponse,
    PlatformAuditLogRow,
    PlatformStatusResponse,
    PlatformTenantDetailResponse,
    PlatformTenantListResponse,
    PlatformTenantRow,
    PlatformTenantSections,
    PlatformTenantUsageResponse,
    PlatformUsageListResponse,
    PlatformUsageRowBody,
    QueueDepthBody,
    QuotaOverrideBody,
    ReplicaCountBody,
    TenantPlanSection,
    TenantPlanSectionData,
    TenantStatusSection,
    TenantStatusSectionData,
    TenantUsageSection,
    TenantUsageSectionData,
    TenantWorkloadBody,
    UpdatePlanRequest,
)
from graphrec.common.config import Settings
from graphrec.common.enums import (
    AuditAction,
    MeasurementStatus,
    PlatformPermission,
    Severity,
    TenantStatus,
    UsageType,
)
from graphrec.db.models import Tenant
from graphrec.domain import audit, platform

router = APIRouter(prefix="/platform", tags=["platform"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]

#: One `Annotated` alias per permission, so a route reads as a sentence and a
#: reviewer comparing this file to §12.10's table can do it line by line.
RequirePlatform = Annotated[
    PlatformPrincipal, Depends(require_permission(PlatformPermission.PLATFORM))
]
RequirePlanManagement = Annotated[
    PlatformPrincipal, Depends(require_permission(PlatformPermission.PLAN_MANAGEMENT))
]
RequirePlatformScope = Annotated[
    PlatformPrincipal, Depends(require_permission(PlatformPermission.PLATFORM_SCOPE))
]
RequireMonitoring = Annotated[
    PlatformPrincipal, Depends(require_permission(PlatformPermission.MONITORING))
]
RequireAudit = Annotated[PlatformPrincipal, Depends(require_permission(PlatformPermission.AUDIT))]


# ---------------------------------------------------------------- tenants


@router.get("/tenants", response_model=PlatformTenantListResponse, summary="The estate")
async def list_tenants(
    principal: RequirePlatform,
    tenant_status: Annotated[TenantStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PlatformTenantListResponse:
    page = await platform.list_tenants(
        principal.session, status=tenant_status, search=search, limit=limit, offset=offset
    )
    return PlatformTenantListResponse(
        tenants=[_tenant_row(row) for row in page.rows],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/tenants/{tenant_id}",
    response_model=PlatformTenantDetailResponse,
    summary="One tenant, in three separately-permitted sections",
)
async def tenant_detail(
    tenant_id: uuid.UUID,
    principal: RequirePlatform,
    request: Request,
) -> PlatformTenantDetailResponse:
    """`200` with sections withheld — never a whole-route `403` (L1436).

    The route is gated on `platform permission` alone. The plan and usage
    sections are looked up only when their permission is held, so a withheld
    section costs no query as well as revealing nothing.
    """
    tenant = await platform.require_tenant(principal.session, tenant_id)
    detail = await platform.tenant_detail(
        principal.session,
        tenant,
        counters=request.app.state.usage_counters,
        may_manage_plans=principal.holds(PlatformPermission.PLAN_MANAGEMENT),
        may_read_usage=principal.holds(PlatformPermission.PLATFORM_SCOPE),
    )
    return PlatformTenantDetailResponse(
        tenant=_tenant_row(detail.tenant),
        sections=PlatformTenantSections(
            status=TenantStatusSection(
                granted=True,
                data=TenantStatusSectionData(
                    status=TenantStatus(detail.status.payload.status),
                    status_changed_at=detail.status.payload.status_changed_at,
                    status_reason=detail.status.payload.status_reason,
                    created_at=detail.status.payload.created_at,
                    is_operable=detail.status.payload.is_operable,
                ),
            ),
            plan=_plan_section(detail.plan),
            usage=_usage_section(detail.usage),
        ),
    )


@router.post(
    "/tenants/{tenant_id}:status",
    response_model=PlatformTenantRow,
    summary="Move a tenant between lifecycle states",
)
async def change_tenant_status(
    tenant_id: uuid.UUID,
    body: ChangeTenantStatusRequest,
    principal: RequirePlatform,
    trail: PlatformAudit,
) -> PlatformTenantRow:
    """Audited as `tenant`, and the audit row names the tenant it concerns.

    `tenant_id` is set, so the row appears on the platform audit page *and* on
    the tenant's own — which is the right answer to "why did my account stop
    working": an account being suspended is something its owner is entitled to
    see recorded. What they do not see is who did it. `AuditRow`'s five columns
    omit `actor_id`, so the tenant reads `platform_user` and a timestamp, never
    an operator's identity.
    """
    tenant = await platform.require_tenant(principal.session, tenant_id)
    concerning = trail.concerning(tenant_id)
    async with concerning.action(
        AuditAction.TENANT, resource_type="tenant", resource_ref=tenant_id
    ) as entry:
        previous = tenant.status
        await platform.change_status(
            principal.session, tenant, status=body.status, reason=body.reason
        )
        entry.details = {
            "operation": "change_status",
            "from": previous,
            "to": body.status.value,
            # The reason is a person's sentence about a customer and it is the
            # point of the row, so it is stored — `safe_details` redacts keys
            # that name secrets, and this names none.
            "reason": body.reason,
        }
    return _tenant_row(_summary_of(tenant))


@router.get(
    "/tenants/{tenant_id}/usage",
    response_model=PlatformTenantUsageResponse,
    summary="One tenant's aggregate usage",
)
async def tenant_usage(
    tenant_id: uuid.UUID, principal: RequirePlatformScope
) -> PlatformTenantUsageResponse:
    rows = await platform.tenant_usage(principal.session, tenant_id=tenant_id)
    return PlatformTenantUsageResponse(
        tenant_id=tenant_id,
        tenant_code=rows[0].tenant_code,
        period=rows[0].period,
        rows=[_usage_row(row) for row in rows],
    )


@router.post(
    "/tenants/{tenant_id}:assign-plan",
    response_model=PlatformTenantRow,
    summary="Put a tenant on a plan",
)
async def assign_plan(
    tenant_id: uuid.UUID,
    body: AssignPlanRequest,
    principal: RequirePlanManagement,
    trail: PlatformAudit,
) -> PlatformTenantRow:
    tenant = await platform.require_tenant(principal.session, tenant_id)
    plan = await platform.require_plan(principal.session, body.plan_id)
    concerning = trail.concerning(tenant_id)
    async with concerning.action(
        AuditAction.TENANT, resource_type="tenant_subscription", resource_ref=tenant_id
    ) as entry:
        subscription = await platform.assign_plan(
            principal.session,
            tenant,
            plan=plan,
            assigned_by=principal.user_id,
            reason=body.reason,
        )
        entry.resource_ref = subscription.subscription_id
        entry.details = {"operation": "assign_plan", "plan_code": plan.plan_code}
    await principal.session.refresh(tenant, ["plan"])
    return _tenant_row(_summary_of(tenant))


@router.post(
    "/tenants/{tenant_id}/quota-overrides",
    response_model=QuotaOverrideBody,
    status_code=status.HTTP_201_CREATED,
    summary="Grant an exception above the plan's limit",
)
async def grant_override(
    tenant_id: uuid.UUID,
    body: GrantOverrideRequest,
    principal: RequirePlanManagement,
    trail: PlatformAudit,
) -> QuotaOverrideBody:
    """Audited as `quota` — one of ER-F-11's eight actions."""
    tenant = await platform.require_tenant(principal.session, tenant_id)
    concerning = trail.concerning(tenant_id)
    async with concerning.action(AuditAction.QUOTA, resource_type="quota_override") as entry:
        override = await platform.grant_override(
            principal.session,
            tenant,
            usage_type=body.usage_type,
            limit_value=body.limit_value,
            reason=body.reason,
            granted_by=principal.user_id,
            expires_at=body.expires_at,
        )
        entry.resource_ref = override.override_id
        entry.details = {
            "operation": "grant_override",
            "usage_type": body.usage_type.value,
            "limit_value": body.limit_value,
            "reason": body.reason,
        }
    return QuotaOverrideBody(
        override_id=override.override_id,
        usage_type=UsageType(override.usage_type),
        limit_value=override.limit_value,
        reason=override.reason,
        granted_at=override.granted_at,
        expires_at=override.expires_at,
    )


# ------------------------------------------------------------------ plans


@router.get("/plans", response_model=PlanListResponse, summary="The price list")
async def list_plans(principal: RequirePlanManagement) -> PlanListResponse:
    plans = await platform.list_plans(principal.session)
    return PlanListResponse(plans=[_plan_body(plan) for plan in plans])


@router.post(
    "/plans",
    response_model=PlanBody,
    status_code=status.HTTP_201_CREATED,
    summary="Create a plan",
)
async def create_plan(
    body: CreatePlanRequest, principal: RequirePlanManagement, trail: PlatformAudit
) -> PlanBody:
    async with trail.action(AuditAction.QUOTA, resource_type="pricing_plan") as entry:
        plan = await platform.create_plan(
            principal.session,
            plan_code=body.plan_code,
            plan_name=body.plan_name,
            description=body.description,
            limits=body.limits.model_dump(),
            service_limits=body.service_limits,
        )
        entry.resource_ref = plan.plan_id
        entry.details = {"operation": "create_plan", "plan_code": plan.plan_code}
    detail = await platform.plan_detail(principal.session, plan)
    return _plan_body(detail.plan)


@router.get("/plans/{plan_id}", response_model=PlanDetailResponse, summary="One plan")
async def plan_detail(plan_id: uuid.UUID, principal: RequirePlanManagement) -> PlanDetailResponse:
    plan = await platform.require_plan(principal.session, plan_id)
    detail = await platform.plan_detail(principal.session, plan)
    return PlanDetailResponse(
        plan=_plan_body(detail.plan),
        tenants=[
            AssignedTenantBody(
                tenant_id=row.tenant_id,
                tenant_code=row.tenant_code,
                tenant_name=row.tenant_name,
                status=TenantStatus(row.status),
            )
            for row in detail.tenants
        ],
    )


@router.patch("/plans/{plan_id}", response_model=PlanBody, summary="Edit a plan's limits")
async def update_plan(
    plan_id: uuid.UUID,
    body: UpdatePlanRequest,
    principal: RequirePlanManagement,
    trail: PlatformAudit,
) -> PlanBody:
    """A plan's limits are not versioned — see `domain/platform/plans.py`.

    The audit row therefore carries the figures that were set, which is the only
    record that the old ones ever existed.
    """
    plan = await platform.require_plan(principal.session, plan_id)
    async with trail.action(
        AuditAction.QUOTA, resource_type="pricing_plan", resource_ref=plan_id
    ) as entry:
        limits = body.limits.model_dump() if body.limits is not None else None
        await platform.update_plan(
            principal.session,
            plan,
            plan_name=body.plan_name,
            description=body.description,
            limits=limits,
            service_limits=body.service_limits,
        )
        entry.details = {"operation": "update_plan", "plan_code": plan.plan_code} | (
            {name: str(value) for name, value in limits.items()} if limits else {}
        )
    detail = await platform.plan_detail(principal.session, plan)
    return _plan_body(detail.plan)


@router.post(
    "/plans/{plan_id}:close", response_model=PlanBody, summary="Close a plan to new assignments"
)
async def close_plan(
    plan_id: uuid.UUID, principal: RequirePlanManagement, trail: PlatformAudit
) -> PlanBody:
    """Reversible, and it does not evict the plan's existing tenants (L1496)."""
    plan = await platform.require_plan(principal.session, plan_id)
    async with trail.action(
        AuditAction.QUOTA, resource_type="pricing_plan", resource_ref=plan_id
    ) as entry:
        await platform.close_plan(principal.session, plan)
        entry.details = {"operation": "close_plan", "plan_code": plan.plan_code}
    detail = await platform.plan_detail(principal.session, plan)
    return _plan_body(detail.plan)


# ------------------------------------------------------------------ usage


@router.get("/usage", response_model=PlatformUsageListResponse, summary="Cross-tenant usage")
async def cross_tenant_usage(
    principal: RequirePlatformScope,
    tenant: uuid.UUID | None = None,
    usage_type: UsageType | None = None,
    period: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PlatformUsageListResponse:
    """Aggregate quantities only; a named tenant that does not exist is a 404.

    "Rejected, not shown as an empty row" (L1524) — an empty page reads as "that
    tenant used nothing", which is an answer, and the operator investigating a
    billing dispute would act on it.
    """
    rows, total = await platform.cross_tenant_usage(
        principal.session,
        tenant_id=tenant,
        usage_type=usage_type,
        period=period,
        limit=limit,
        offset=offset,
    )
    return PlatformUsageListResponse(
        rows=[_usage_row(row) for row in rows], total=total, limit=limit, offset=offset
    )


# ----------------------------------------------------------------- status


@router.get("/status", response_model=PlatformStatusResponse, summary="Installation health")
async def platform_status(
    principal: RequireMonitoring,
    settings: SettingsDep,
    window_hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> PlatformStatusResponse:
    board = await platform.platform_status(
        principal.session,
        training_concurrency=settings.training_global_concurrency,
        window=dt.timedelta(hours=window_hours),
    )
    return PlatformStatusResponse(
        window_hours=board.window_hours,
        serving_availability=board.serving_availability,
        training_queue=QueueDepthBody(
            running=board.training_queue.running,
            waiting=board.training_queue.waiting,
            concurrency=board.training_queue.concurrency,
        ),
        replicas=ReplicaCountBody(ready=board.replicas.ready, desired=board.replicas.desired),
        ingestion_lag_seconds=board.ingestion_lag_seconds,
        failures_24h=board.failures_24h,
        active_tenants=board.active_tenants,
        workload_by_tenant=[
            TenantWorkloadBody(
                tenant_id=row.tenant_id,
                tenant_code=row.tenant_code,
                running_jobs=row.running_jobs,
                queued_jobs=row.queued_jobs,
                desired_replicas=row.desired_replicas,
                ready_replicas=row.ready_replicas,
            )
            for row in board.workload_by_tenant
        ],
        failure_summary=[
            FailureSummaryBody(area=row.area, severity=row.severity, count=row.count)
            for row in board.failure_summary
        ],
        measurement_gaps=[
            MeasurementGapBody(quantity=gap.quantity, reason=gap.reason)
            for gap in board.measurement_gaps
        ],
    )


# ------------------------------------------------------------------ audit


@router.get("/failures", response_model=FailureListResponse, summary="Terminal failures, redacted")
async def list_failures(
    principal: RequireAudit,
    severity: Severity | None = None,
    occurred_after: dt.datetime | None = None,
    tenant: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FailureListResponse:
    """Tenant identity is redacted unless the caller arrived from a tenant.

    `reveal_tenant` follows `tenant` rather than being its own flag: an operator
    who passed a tenant id already knows which tenant they are looking at, and
    volunteering the column on the unfiltered list would turn a severity
    ranking into a table of which customers are struggling (L1550).
    """
    page = await audit.failures(
        principal.session,
        severity=severity,
        occurred_after=occurred_after,
        tenant_id=tenant,
        reveal_tenant=tenant is not None,
        limit=limit,
        offset=offset,
    )
    return FailureListResponse(
        failures=[
            FailureRowBody(
                occurred_at=row.occurred_at,
                severity=row.severity,
                area=row.area,
                summary=row.summary,
                reference=row.reference,
                tenant_id=row.tenant_id,
            )
            for row in page.rows
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/audit-logs", response_model=PlatformAuditListResponse, summary="Every tenant's history"
)
async def list_audit_logs(
    principal: RequireAudit,
    tenant: uuid.UUID | None = None,
    action: AuditAction | None = None,
    occurred_after: dt.datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PlatformAuditListResponse:
    page = await audit.platform_page(
        principal.session,
        tenant_id=tenant,
        action=action,
        occurred_after=occurred_after,
        limit=limit,
        offset=offset,
    )
    return PlatformAuditListResponse(
        entries=[
            PlatformAuditLogRow(
                occurred_at=row.occurred_at,
                tenant_id=row.tenant_id,
                actor_type=row.actor_type,
                actor_id=row.actor_id,
                action=row.action,
                resource_type=row.resource_type,
                resource_ref=row.resource_ref,
                outcome=row.outcome,
                correlation_ref=row.correlation_ref,
            )
            for row in page.rows
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


# ---------------------------------------------------------------- helpers


def _tenant_row(summary: platform.TenantSummary) -> PlatformTenantRow:
    return PlatformTenantRow(
        tenant_id=summary.tenant_id,
        tenant_code=summary.tenant_code,
        tenant_name=summary.tenant_name,
        status=TenantStatus(summary.status),
        plan_code=summary.plan_code,
        created_at=summary.created_at,
    )


def _summary_of(tenant: Tenant) -> platform.TenantSummary:
    """The ORM row as the summary the wire model is built from.

    Written out rather than reusing `list_tenants`' projection because a write
    handler has the row in hand and re-querying for it would be a second read
    of something it just changed.
    """
    return platform.TenantSummary(
        tenant_id=tenant.tenant_id,
        tenant_code=tenant.tenant_code,
        tenant_name=tenant.tenant_name,
        status=tenant.status,
        plan_code=tenant.plan.plan_code if tenant.plan is not None else None,
        created_at=tenant.created_at,
    )


def _plan_section(section: platform.Section[platform.PlanSection]) -> TenantPlanSection:
    """A withheld section carries its reason and no data — and vice versa.

    The two are never both present. A `granted: false` that also carried data
    would be a permission check the client could ignore by reading past it.
    """
    if not section.granted:
        return TenantPlanSection(granted=False, reason=section.reason)
    data = section.payload
    return TenantPlanSection(
        granted=True,
        data=TenantPlanSectionData(
            plan_id=data.plan_id,
            plan_code=data.plan_code,
            plan_name=data.plan_name,
            assigned_at=data.assigned_at,
            overrides=[
                QuotaOverrideBody(
                    override_id=row.override_id,
                    usage_type=UsageType(row.usage_type),
                    limit_value=row.limit_value,
                    reason=row.reason,
                    granted_at=row.granted_at,
                    expires_at=row.expires_at,
                )
                for row in data.overrides
            ],
        ),
    )


def _usage_section(section: platform.Section[platform.UsageSection]) -> TenantUsageSection:
    if not section.granted:
        return TenantUsageSection(granted=False, reason=section.reason)
    data = section.payload
    return TenantUsageSection(
        granted=True,
        data=TenantUsageSectionData(
            period=data.period, rows=[_usage_row(row) for row in data.rows]
        ),
    )


def _usage_row(row: platform.PlatformUsageRow) -> PlatformUsageRowBody:
    return PlatformUsageRowBody(
        tenant_id=row.tenant_id,
        tenant_code=row.tenant_code,
        period=row.period,
        usage_type=UsageType(row.usage_type),
        quantity=row.quantity,
        measurement_status=MeasurementStatus(row.measurement_status),
    )


def _plan_body(summary: platform.PlanSummary) -> PlanBody:
    return PlanBody(
        plan_id=summary.plan_id,
        plan_code=summary.plan_code,
        plan_name=summary.plan_name,
        description=summary.description,
        event_limit=summary.event_limit,
        recommendation_limit=summary.recommendation_limit,
        training_limit=summary.training_limit,
        product_limit=summary.product_limit,
        storage_limit_bytes=summary.storage_limit_bytes,
        service_limits=summary.service_limits,
        accepts_assignments=summary.is_active,
        assigned_tenants=summary.assigned_tenants,
    )


__all__ = ["router"]
