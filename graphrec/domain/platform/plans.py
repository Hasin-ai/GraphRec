"""The price list. Shared across tenants, written only by plan management.

`pricing_plans` is the one business table with no `tenant_id`, and everything
odd about this module follows from that. There is no RLS scoping to lean on, so
the protection is entirely the grant: `graphrec_app` reads plans and cannot
write them, `graphrec_platform` writes them, and a tenant-realm request has no
path to this code at all.

Two design points worth stating, because both look like omissions:

**Limits are not versioned.** Editing a plan changes what its tenants are
entitled to, immediately, with no record of what the limit was yesterday. That
is what L1635's form describes, and the audit row for the edit carries the new
figures — but a tenant's historical usage is measured against a limit that may
since have moved, and nothing here reconstructs the old one. Called out rather
than hidden: a billing dispute six months old cannot be settled from this table.

**Closing is reversible and does not evict.** `is_active=false` refuses new
assignments (L1454) and nothing else. Tenants on a closed plan keep it, keep
their limits, and can be re-assigned to it. A close that unpriced its members
would be a billing outage triggered by a tidy-up.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from graphrec.common.errors import ConflictError, NotFoundError, ValidationError
from graphrec.common.ids import uuid7
from graphrec.db.models import PricingPlan, Tenant

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

#: The five limit columns, in the order the console's form renders them, and
#: the only fields `update_plan` will move. `service_limits` is edited as a
#: whole object; `plan_code` is not editable at all, because tenants and audit
#: rows refer to plans by it.
LIMIT_FIELDS = (
    "event_limit",
    "recommendation_limit",
    "training_limit",
    "product_limit",
    "storage_limit_bytes",
)


@dataclass(frozen=True, slots=True)
class PlanSummary:
    """One row of `/admin/plans` (L1439)."""

    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    description: str | None
    event_limit: int
    recommendation_limit: int
    training_limit: int
    product_limit: int
    storage_limit_bytes: int
    service_limits: dict[str, Any]
    is_active: bool
    assigned_tenants: int


@dataclass(frozen=True, slots=True)
class AssignedTenant:
    tenant_id: uuid.UUID
    tenant_code: str
    tenant_name: str
    status: str


@dataclass(frozen=True, slots=True)
class PlanDetail:
    plan: PlanSummary
    tenants: list[AssignedTenant]


async def list_plans(session: AsyncSession, *, include_closed: bool = True) -> list[PlanSummary]:
    """Every plan, with the number of tenants on each.

    The count is part of the list rather than the detail because it is what an
    operator needs before closing one: a plan with forty tenants and a plan with
    none are the same row otherwise, and only one of them is safe to tidy away.
    """
    assigned = (
        sa.select(Tenant.plan_id, sa.func.count().label("assigned"))
        .group_by(Tenant.plan_id)
        .subquery()
    )
    statement = (
        sa.select(PricingPlan, sa.func.coalesce(assigned.c.assigned, 0))
        .join(assigned, assigned.c.plan_id == PricingPlan.plan_id, isouter=True)
        .order_by(PricingPlan.plan_code)
    )
    if not include_closed:
        statement = statement.where(PricingPlan.is_active.is_(True))

    result = await session.execute(statement)
    return [_summary(plan, count) for plan, count in result.all()]


async def require_plan(session: AsyncSession, plan_id: uuid.UUID) -> PricingPlan:
    plan = await session.get(PricingPlan, plan_id)
    if plan is None:
        raise NotFoundError()
    return plan


async def plan_detail(session: AsyncSession, plan: PricingPlan) -> PlanDetail:
    result = await session.execute(
        sa.select(Tenant.tenant_id, Tenant.tenant_code, Tenant.tenant_name, Tenant.status)
        .where(Tenant.plan_id == plan.plan_id)
        .order_by(Tenant.tenant_code)
    )
    tenants = [AssignedTenant(*row) for row in result.all()]
    return PlanDetail(plan=_summary(plan, len(tenants)), tenants=tenants)


async def create_plan(
    session: AsyncSession,
    *,
    plan_code: str,
    plan_name: str,
    description: str | None,
    limits: dict[str, int],
    service_limits: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> PricingPlan:
    """A new plan, open to assignment from the moment it exists.

    The uniqueness of `plan_code` is enforced by the index; the check here is
    the courteous version of the same refusal, and the index is the one that is
    actually race-proof.
    """
    moment = now or dt.datetime.now(dt.UTC)
    code = plan_code.strip().upper()
    if not code:
        raise ValidationError("plan_code_required").with_field("plan_code", "Required.")
    _reject_negative(limits)

    existing = await session.scalar(
        sa.select(PricingPlan.plan_id).where(PricingPlan.plan_code == code)
    )
    if existing is not None:
        raise ConflictError("plan_code_already_exists").with_field("plan_code", "Already in use.")

    plan = PricingPlan(
        plan_id=uuid7(),
        plan_code=code,
        plan_name=plan_name.strip(),
        description=(description.strip() if description else None),
        service_limits=service_limits or {},
        is_active=True,
        created_at=moment,
        updated_at=moment,
        **limits,
    )
    session.add(plan)
    await session.flush()
    return plan


async def update_plan(
    session: AsyncSession,
    plan: PricingPlan,
    *,
    plan_name: str | None = None,
    description: str | None = None,
    limits: dict[str, int] | None = None,
    service_limits: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> PricingPlan:
    """Edit limits and naming. `plan_code` is deliberately not editable.

    Every field is optional and only the supplied ones move, so a form that
    renders five limits and submits three does not silently zero the other two —
    and zero is a meaningful limit here, which is exactly why "absent" and
    "zero" must not be the same value on the wire.
    """
    moment = now or dt.datetime.now(dt.UTC)
    if limits:
        _reject_negative(limits)
        for name, value in limits.items():
            setattr(plan, name, value)
    if plan_name is not None:
        plan.plan_name = plan_name.strip()
    if description is not None:
        plan.description = description.strip() or None
    if service_limits is not None:
        plan.service_limits = service_limits
    plan.updated_at = moment
    await session.flush()
    return plan


async def close_plan(
    session: AsyncSession, plan: PricingPlan, *, now: dt.datetime | None = None
) -> PricingPlan:
    """Refuse new assignments. Reversible, and does not touch existing ones."""
    if not plan.is_active:
        raise ConflictError("plan_already_closed")
    plan.is_active = False
    plan.updated_at = now or dt.datetime.now(dt.UTC)
    await session.flush()
    return plan


async def reopen_plan(
    session: AsyncSession, plan: PricingPlan, *, now: dt.datetime | None = None
) -> PricingPlan:
    """The other half of `close_plan`.

    L1496 calls closing reversible and the prototype's dialog says "Reopen the
    plan or choose another" in the refusal a closed plan produces — a sentence
    that names an action the API had better offer.
    """
    if plan.is_active:
        return plan
    plan.is_active = True
    plan.updated_at = now or dt.datetime.now(dt.UTC)
    await session.flush()
    return plan


def _reject_negative(limits: dict[str, int]) -> None:
    """L1635, and SRS §5.2.1 under it.

    Reported per field rather than as one banner, because the form has five
    inputs and an operator who typed `-1` into one of them should be shown
    which.
    """
    offenders = [name for name, value in limits.items() if value < 0]
    if not offenders:
        return
    error = ValidationError("negative_limit")
    for name in offenders:
        error.with_field(name, "Must be zero or greater.")
    raise error


def _summary(plan: PricingPlan, assigned: int) -> PlanSummary:
    return PlanSummary(
        plan_id=plan.plan_id,
        plan_code=plan.plan_code,
        plan_name=plan.plan_name,
        description=plan.description,
        event_limit=plan.event_limit,
        recommendation_limit=plan.recommendation_limit,
        training_limit=plan.training_limit,
        product_limit=plan.product_limit,
        storage_limit_bytes=plan.storage_limit_bytes,
        service_limits=plan.service_limits or {},
        is_active=plan.is_active,
        assigned_tenants=assigned,
    )


__all__ = [
    "LIMIT_FIELDS",
    "AssignedTenant",
    "PlanDetail",
    "PlanSummary",
    "close_plan",
    "create_plan",
    "list_plans",
    "plan_detail",
    "reopen_plan",
    "require_plan",
    "update_plan",
]
