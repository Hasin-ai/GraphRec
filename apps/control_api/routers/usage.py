"""Usage, quotas and the plan — three reads, all administrator-only.

`/usage` is declared `[ADMIN]` in the prototype's route table (dc.html L650),
and L1256 states the two roles plainly: an administrator holds "usage, quota and
service status", a developer has "No training, model, usage or service status
access." So gate 3 here is `TENANT_ADMINISTRATOR`, and a developer's token gets
a 403 rather than a filtered page.

`/subscription` lives here rather than under `/tenants` because it answers the
usage page's kicker — "Plan GROWTH" (L1805) — and because entitlements and usage
are the same question asked twice. It is read-only and has no write counterpart:
plan assignment is UC-28, a platform action (ROUTES L178).

Nothing in this module substitutes a number it does not have. Every nullable
field arriving from the domain is passed through as `null`, with
`measurement_status` carrying the explanation. There is no `or 0` in this file
and none may be added.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from apps.control_api.deps import RequireAdministrator, UsageCountersDep
from apps.control_api.schemas import (
    EntitlementBody,
    SubscriptionResponse,
    UsageItemBody,
    UsagePeriodBody,
    UsageResponse,
    UsageTrendRowBody,
    UsageTrendsResponse,
)
from graphrec.domain import quotas
from graphrec.domain.metering import service as metering

router = APIRouter(tags=["metering"])

#: The prototype's period filter offers "current period", "previous period" and
#: "last 3 periods" (L1818), and the trend panel renders three rows. Three is
#: therefore the maximum a client can ask for as well as the default.
MAX_TREND_PERIODS = 3


@router.get("/usage", response_model=UsageResponse, summary="Measured usage against limits")
async def read_usage(
    principal: RequireAdministrator,
    counters: UsageCountersDep,
) -> UsageResponse:
    report = await metering.usage(
        principal.session,
        counters,
        tenant_id=principal.tenant_id,
        now=quotas.utcnow(),
    )
    return UsageResponse(
        period=UsagePeriodBody(
            start=report.period.start,
            end=report.period.end,
            label=report.period.reset_label,
        ),
        items=[
            UsageItemBody(
                usage_type=row.usage_type,
                measured=row.measured,
                effective_limit=row.effective_limit,
                remaining=row.remaining,
                reset=row.reset,
                measurement_status=row.status_label,
                limit_source=row.limit_source,
            )
            for row in report.items
        ],
        footnote=report.footnote,
    )


@router.get("/usage/trends", response_model=UsageTrendsResponse, summary="Usage by recent period")
async def read_usage_trends(
    principal: RequireAdministrator,
    counters: UsageCountersDep,
    periods: Annotated[int, Query(ge=1, le=MAX_TREND_PERIODS)] = MAX_TREND_PERIODS,
) -> UsageTrendsResponse:
    rows = await metering.trends(
        principal.session,
        counters,
        tenant_id=principal.tenant_id,
        now=quotas.utcnow(),
        periods=periods,
    )
    return UsageTrendsResponse(
        rows=[
            UsageTrendRowBody(period=row.period.label, label=row.label, quantities=row.quantities)
            for row in rows
        ]
    )


@router.get("/subscription", response_model=SubscriptionResponse, summary="Plan and entitlements")
async def read_subscription(principal: RequireAdministrator) -> SubscriptionResponse:
    plan = await metering.subscription(
        principal.session, tenant_id=principal.tenant_id, now=quotas.utcnow()
    )
    return SubscriptionResponse(
        plan_code=plan.plan_code,
        plan_name=plan.plan_name,
        description=plan.description,
        entitlements=[
            EntitlementBody(
                usage_type=item.usage_type,
                plan_limit=item.plan_limit,
                effective_limit=item.effective_limit,
                limit_source=item.limit_source,
            )
            for item in plan.entitlements
        ],
    )
