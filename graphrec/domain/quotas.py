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

Metering (Phase 7) adds the *usage* half. This is only the limit.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

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


async def effective_limit(
    session: AsyncSession, *, tenant_id: uuid.UUID, usage_type: UsageType, now: dt.datetime
) -> int | None:
    """The limit in force, or `None` when the usage type is not bounded.

    Runs inside the caller's tenant-bound session, so `quota_overrides` and
    `tenant_resource_quotas` are filtered by the tenant's own policy and the
    `tenant_id` argument is only used to read the plan — which is not
    tenant-owned and is joined through `tenants`.
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
        return int(override)

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
        return int(standing)

    column = PLAN_LIMIT_COLUMN.get(usage_type)
    if column is None:
        return None

    # `column` is a value of PLAN_LIMIT_COLUMN, never caller input.
    plan_limit = await session.scalar(
        sa.text(
            f"SELECT p.{column} FROM pricing_plans AS p "
            "JOIN tenants AS t ON t.plan_id = p.plan_id "
            "WHERE t.tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    return None if plan_limit is None else int(plan_limit)


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


__all__ = ["PLAN_LIMIT_COLUMN", "effective_limit", "plan_code", "utcnow"]
