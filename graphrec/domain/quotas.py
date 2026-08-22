"""Resolving the limit that actually applies to a tenant.

Three sources, in precedence order (BACKEND_PLAN §14, `pg_pTenant` L1430):

1. an **active quota override** — granted by a platform administrator, and the
   thing the console tells a tenant to go and ask for when they run out
   (L1603: "ask your platform contact about a quota override");
2. a **tenant resource quota** — a standing per-tenant figure for the current
   period;
3. the **plan's** limit.

Phase 5 needs exactly one of these — the product count — and this module is
deliberately the whole answer for all of them rather than a product-shaped
special case, because the second caller is a fortnight away and a second
implementation is how the console comes to quote a number the enforcement does
not use.

Metering (Phase 7) adds the *usage* half — `graphrec.domain.metering.quota`.
This module is only the limit.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import sqlalchemy as sa

from graphrec.common.enums import UsageType

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

#: `pricing_plans` column per usage type. Only the types a plan bounds appear;
#: `service_capacity` is measured, not granted (dc.html L1824).
PLAN_LIMIT_COLUMN: dict[UsageType, str] = {
    UsageType.EVENTS: "event_limit",
    UsageType.RECOMMENDATIONS: "recommendation_limit",
    UsageType.TRAINING: "training_limit",
    UsageType.PRODUCTS: "product_limit",
    UsageType.STORAGE: "storage_limit_bytes",
}


#: The wire vocabulary for where a limit came from (BACKEND_PLAN L1195).
#: Only two values, and `tenant_resource_quotas` reports as `override` rather
#: than earning a third. A standing per-tenant quota is, from the tenant's side,
#: exactly what an override is: a limit that is not the one their plan says.
#: Splitting them on the wire would ask the console to explain a distinction
#: that exists only in our schema.
LimitSource = Literal["plan", "override"]


@dataclass(frozen=True, slots=True)
class Limit:
    """A resolved limit and the reason it is that number.

    `value is None` means the usage type is not bounded — `service_capacity` has
    no plan column, so there is nothing to be within.
    """

    value: int | None
    source: LimitSource


async def resolve(
    session: AsyncSession, *, tenant_id: uuid.UUID, usage_type: UsageType, now: dt.datetime
) -> Limit:
    """`effective_limit`, plus what the console needs to label it.

    Precedence is the module docstring's: an active override, then a standing
    tenant quota, then the plan. The first two are tenant-owned and read under
    the tenant's own policy; the plan is joined through `tenants`.
    """
    override = await session.scalar(
        sa.text(
            "SELECT limit_value FROM quota_overrides "
            "WHERE usage_type = :usage_type "
            "  AND revoked_at IS NULL "
            "  AND granted_at <= :now "
            "  AND (expires_at IS NULL OR expires_at > :now) "
            "ORDER BY granted_at DESC LIMIT 1"
        ),
        {"usage_type": usage_type.value, "now": now},
    )
    if override is not None:
        return Limit(int(override), "override")

    standing = await session.scalar(
        sa.text(
            "SELECT limit_value FROM tenant_resource_quotas "
            "WHERE usage_type = :usage_type "
            "  AND period_start <= :now "
            "  AND (period_end IS NULL OR period_end > :now) "
            "ORDER BY period_start DESC LIMIT 1"
        ),
        {"usage_type": usage_type.value, "now": now},
    )
    if standing is not None:
        return Limit(int(standing), "override")

    column = PLAN_LIMIT_COLUMN.get(usage_type)
    if column is None:
        return Limit(None, "plan")

    # `column` is a value of PLAN_LIMIT_COLUMN, never caller input.
    plan_limit = await session.scalar(
        sa.text(
            f"SELECT p.{column} FROM pricing_plans AS p "
            "JOIN tenants AS t ON t.plan_id = p.plan_id "
            "WHERE t.tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    return Limit(None if plan_limit is None else int(plan_limit), "plan")


async def effective_limit(
    session: AsyncSession, *, tenant_id: uuid.UUID, usage_type: UsageType, now: dt.datetime
) -> int | None:
    """The limit in force, or `None` when the usage type is not bounded.

    The bare number, for callers that only enforce. `resolve` is the same
    lookup for callers that also have to say where it came from.
    """
    limit = await resolve(session, tenant_id=tenant_id, usage_type=usage_type, now=now)
    return limit.value


async def plan_code(session: AsyncSession, *, tenant_id: uuid.UUID) -> str:
    """The plan code the quota message names — "on plan GROWTH" (L1603)."""
    code = await session.scalar(
        sa.text(
            "SELECT p.plan_code FROM pricing_plans AS p "
            "JOIN tenants AS t ON t.plan_id = p.plan_id "
            "WHERE t.tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    return str(code) if code is not None else "—"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


__all__ = [
    "PLAN_LIMIT_COLUMN",
    "Limit",
    "LimitSource",
    "effective_limit",
    "plan_code",
    "resolve",
    "utcnow",
]
