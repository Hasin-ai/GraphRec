"""The estate: who exists, what state they are in, and the writes that move it.

The composition rule is the interesting part of this module. `tenant_detail`
takes three booleans rather than a principal, and returns a `TenantDetail` whose
plan and usage sections are `Section` objects that may hold data or a reason.
Two things follow from that shape, both deliberate:

* **A missing permission is not an error.** L1436 and `FRONTEND_BUILD_PROMPT`
  §4 both say a holder of only `platform permission` sees the page with the
  other sections withheld. Raising `ForbiddenError` would force the console to
  make three calls and decide which `403`s are fatal, and the one that decides
  wrong renders an empty page for an operator who was entitled to two thirds of
  it.
* **The withheld reason comes from the server.** The console never composes a
  sentence about a permission it does not hold; it renders the one it was given.
  That is the same discipline every other refusal in this system follows, and it
  is why `WITHHELD_SECTION_COPY` is in the copy catalogue and not here.

The three booleans are passed rather than a `PlatformPrincipal` because this
module is in `graphrec.domain` and the principal is an HTTP concern. It also
makes the composition trivially testable: eight combinations, no tokens.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

import sqlalchemy as sa

from graphrec.common.enums import TenantStatus, UsageType
from graphrec.common.error_copy import WITHHELD_SECTION_COPY
from graphrec.common.errors import ConflictError, NotFoundError, ValidationError
from graphrec.common.ids import uuid7
from graphrec.db.models import PricingPlan, QuotaOverride, Tenant, TenantSubscription
from graphrec.domain.platform.usage import PlatformUsageRow, tenant_usage

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

#: The console's page size for `/admin/tenants`, and the ceiling above it.
MAX_LIMIT = 200

#: The payload of one gated section. Generic so that a handler reading
#: `detail.plan.payload.overrides` is checked rather than trusted — the whole
#: value of composing sections in the domain is lost if the wire layer has to
#: cast its way back to a type.
T = TypeVar("T")

#: Every transition the prototype's dialog offers (L1420). Any status may move
#: to any other, including back out of `deleted`: the prototype describes
#: `deleting` and `deleted` as states a Platform Administrator sets, and nothing
#: in it says a mistake cannot be undone. What is *not* offered is a transition
#: to the status the tenant already holds — see `change_status`.
ASSIGNABLE_STATUSES = frozenset(TenantStatus)


@dataclass(frozen=True, slots=True)
class TenantSummary:
    """One row of `/admin/tenants` — the five columns L1418 lists."""

    tenant_id: uuid.UUID
    tenant_code: str
    tenant_name: str
    status: str
    plan_code: str | None
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class TenantPage:
    rows: list[TenantSummary]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class StatusSection:
    """Status and lifecycle. Held by `platform permission`, so always granted
    here: the route itself is gated on that permission."""

    status: str
    status_changed_at: dt.datetime | None
    status_reason: str | None
    created_at: dt.datetime
    is_operable: bool


@dataclass(frozen=True, slots=True)
class OverrideRow:
    """One approved quota override, with the period it is effective for (L1450).

    `expires_at` of `None` means open-ended, which the console renders as
    "no end date" rather than as a blank — an override with no visible end is
    how a temporary exception becomes permanent by accident.
    """

    override_id: uuid.UUID
    usage_type: str
    limit_value: int
    reason: str
    granted_at: dt.datetime
    expires_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class PlanSection:
    """Plan assignment and the overrides on top of it."""

    plan_id: uuid.UUID | None
    plan_code: str | None
    plan_name: str | None
    assigned_at: dt.datetime | None
    overrides: list[OverrideRow]


@dataclass(frozen=True, slots=True)
class UsageSection:
    """The usage summary, aggregate quantities only."""

    period: str
    rows: list[PlatformUsageRow]


@dataclass(frozen=True, slots=True)
class Section(Generic[T]):
    """One gated section of the composed detail.

    Exactly one of `data` and `reason` is set, and which one is `granted`. The
    two-field shape is what lets the console render a withheld section as a
    labelled placeholder in place, rather than as a hole it has to explain.
    """

    granted: bool
    data: T | None = None
    reason: str | None = None

    @classmethod
    def held(cls, data: T) -> Section[T]:
        return cls(granted=True, data=data)

    @classmethod
    def withheld(cls, permission: str) -> Section[T]:
        return cls(granted=False, reason=WITHHELD_SECTION_COPY[permission])

    @property
    def payload(self) -> T:
        """The data, for a caller that has already checked `granted`.

        Raises rather than returning `None` so that a serialiser which forgot
        the check fails in a test rather than emitting `null` for a section the
        operator was entitled to see.
        """
        if self.data is None:
            msg = "section is withheld; check `granted` before reading `payload`"
            raise RuntimeError(msg)
        return self.data


@dataclass(frozen=True, slots=True)
class TenantDetail:
    """The composed page: one tenant and its three separately-gated sections.

    Three named fields rather than a map, for the same reason the wire model
    uses three: a section that changed shape should break a caller at type-check
    time, and `sections["plan"]` is a string lookup that never will.
    """

    tenant: TenantSummary
    status: Section[StatusSection]
    plan: Section[PlanSection]
    usage: Section[UsageSection]


# ------------------------------------------------------------------ reads


async def list_tenants(
    session: AsyncSession,
    *,
    status: TenantStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> TenantPage:
    """The estate, filtered. Runs unbound, and is meant to."""
    limit = min(max(limit, 1), MAX_LIMIT)
    conditions: list[Any] = []
    if status is not None:
        conditions.append(Tenant.status == status.value)
    if search:
        # Case-insensitive on both the code and the name, because an operator
        # given a tenant code by a support ticket and an operator given a
        # business name by a colleague are the same operator.
        pattern = f"%{search.strip()}%"
        conditions.append(
            sa.or_(Tenant.tenant_code.ilike(pattern), Tenant.tenant_name.ilike(pattern))
        )

    total = await session.scalar(sa.select(sa.func.count()).select_from(Tenant).where(*conditions))
    result = await session.execute(
        sa.select(
            Tenant.tenant_id,
            Tenant.tenant_code,
            Tenant.tenant_name,
            Tenant.status,
            PricingPlan.plan_code,
            Tenant.created_at,
        )
        .select_from(Tenant)
        .join(PricingPlan, PricingPlan.plan_id == Tenant.plan_id, isouter=True)
        .where(*conditions)
        .order_by(Tenant.created_at.desc(), Tenant.tenant_id)
        .limit(limit)
        .offset(offset)
    )
    return TenantPage(
        rows=[TenantSummary(*row) for row in result.all()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


async def require_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    """Load a tenant or raise the same 404 every other missing thing raises.

    Gate 4 applies in the platform realm too, and for a reason that is easy to
    miss: a platform operator holding only `monitoring access` must not be able
    to confirm that a tenant id exists by watching a status code, and the copy
    for `not_found` names no resource type precisely so this one can reuse it.
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError()
    return tenant


async def tenant_detail(
    session: AsyncSession,
    tenant: Tenant,
    *,
    counters: Any,
    may_manage_plans: bool,
    may_read_usage: bool,
    now: dt.datetime | None = None,
) -> TenantDetail:
    """The three-section composition (L1436).

    The status section is unconditional because the route that calls this is
    already gated on `platform permission`; the other two are looked up only
    when they are held, so a withheld section costs no query as well as
    revealing no data.
    """
    moment = now or dt.datetime.now(dt.UTC)
    summary = TenantSummary(
        tenant_id=tenant.tenant_id,
        tenant_code=tenant.tenant_code,
        tenant_name=tenant.tenant_name,
        status=tenant.status,
        plan_code=tenant.plan.plan_code if tenant.plan is not None else None,
        created_at=tenant.created_at,
    )
    status = Section.held(
        StatusSection(
            status=tenant.status,
            status_changed_at=tenant.status_changed_at,
            status_reason=tenant.status_reason,
            created_at=tenant.created_at,
            is_operable=tenant.is_operable,
        )
    )

    plan: Section[PlanSection] = (
        Section.held(await _plan_section(session, tenant, now=moment))
        if may_manage_plans
        else Section.withheld("plan_management")
    )

    if may_read_usage:
        rows = await tenant_usage(session, tenant_id=tenant.tenant_id, now=moment)
        usage: Section[UsageSection] = Section.held(
            UsageSection(period=_period_label(moment), rows=rows)
        )
    else:
        usage = Section.withheld("platform_scope")

    return TenantDetail(tenant=summary, status=status, plan=plan, usage=usage)


async def _plan_section(session: AsyncSession, tenant: Tenant, *, now: dt.datetime) -> PlanSection:
    assigned_at = await session.scalar(
        sa.select(TenantSubscription.started_at)
        .where(
            TenantSubscription.tenant_id == tenant.tenant_id,
            TenantSubscription.ended_at.is_(None),
        )
        .order_by(TenantSubscription.started_at.desc())
        .limit(1)
    )
    result = await session.execute(
        sa.select(
            QuotaOverride.override_id,
            QuotaOverride.usage_type,
            QuotaOverride.limit_value,
            QuotaOverride.reason,
            QuotaOverride.granted_at,
            QuotaOverride.expires_at,
        )
        .where(
            QuotaOverride.tenant_id == tenant.tenant_id,
            QuotaOverride.revoked_at.is_(None),
            sa.or_(QuotaOverride.expires_at.is_(None), QuotaOverride.expires_at > now),
        )
        .order_by(QuotaOverride.granted_at.desc())
    )
    return PlanSection(
        plan_id=tenant.plan_id,
        plan_code=tenant.plan.plan_code if tenant.plan is not None else None,
        plan_name=tenant.plan.plan_name if tenant.plan is not None else None,
        assigned_at=assigned_at,
        overrides=[OverrideRow(*row) for row in result.all()],
    )


def _period_label(moment: dt.datetime) -> str:
    day = moment.astimezone(dt.UTC).date()
    return f"{day.year:04d}-{day.month:02d}"


# ----------------------------------------------------------------- writes


async def change_status(
    session: AsyncSession,
    tenant: Tenant,
    *,
    status: TenantStatus,
    reason: str,
    now: dt.datetime | None = None,
) -> Tenant:
    """Move a tenant between lifecycle states. `reason` is not optional.

    L1420 makes the reason a required field of the dialog, and the reason it is
    required is that it is the only part of this row a person wrote: the status,
    the actor and the timestamp are all mechanical, and a suspension nobody
    explained is one nobody can undo with confidence six months later.

    The effect on serving is not applied here. Setting `desired_replicas` to
    zero needs privileges on `model_deployments` that the platform role does not
    hold — deliberately, since a console that can write a tenant's serving state
    directly is a console that can serve the wrong version. The reconciler reads
    the status on its next pass and scales the tenant down; gate 2 refuses the
    tenant's own requests immediately, which is the part a suspension has to be
    instant about.
    """
    moment = now or dt.datetime.now(dt.UTC)
    if not reason.strip():
        raise ValidationError("reason_required_audited").with_field(
            "reason", "A reason is required."
        )
    if tenant.status == status.value:
        raise ConflictError("tenant_status_unchanged")

    tenant.status = status.value
    tenant.status_reason = reason.strip()
    tenant.status_changed_at = moment
    tenant.updated_at = moment
    await session.flush()
    return tenant


async def assign_plan(
    session: AsyncSession,
    tenant: Tenant,
    *,
    plan: PricingPlan,
    assigned_by: uuid.UUID,
    reason: str | None = None,
    now: dt.datetime | None = None,
) -> TenantSubscription:
    """Put a tenant on a plan, and close the subscription it was on.

    A closed plan refuses **new** assignments only. Re-assigning a tenant to the
    plan it already holds is permitted even when the plan is closed (L1454):
    closing a plan is a statement about who may join it, not a statement that
    its existing members are now unpriced.
    """
    moment = now or dt.datetime.now(dt.UTC)
    if not plan.is_active and tenant.plan_id != plan.plan_id:
        raise ConflictError("plan_closed", copy_args={"plan_code": plan.plan_code})

    await session.execute(
        sa.update(TenantSubscription)
        .where(
            TenantSubscription.tenant_id == tenant.tenant_id,
            TenantSubscription.ended_at.is_(None),
        )
        .values(ended_at=moment)
    )
    subscription = TenantSubscription(
        # Minted here rather than left to the database: `tenant_subscriptions`
        # has no server default, and the identifier is wanted before the flush
        # so the audit row can name what was created.
        subscription_id=uuid7(),
        tenant_id=tenant.tenant_id,
        plan_id=plan.plan_id,
        started_at=moment,
        assigned_by=assigned_by,
        reason=(reason.strip() if reason else None),
    )
    session.add(subscription)
    tenant.plan_id = plan.plan_id
    tenant.updated_at = moment
    await session.flush()
    return subscription


async def grant_override(
    session: AsyncSession,
    tenant: Tenant,
    *,
    usage_type: UsageType,
    limit_value: int,
    reason: str,
    granted_by: uuid.UUID,
    expires_at: dt.datetime | None = None,
    now: dt.datetime | None = None,
) -> QuotaOverride:
    """Grant an exception above the plan's limit, with a period and a reason.

    Zero is a legitimate limit and negative is not (L1462): zero withholds a
    usage type entirely, which is a thing an operator may genuinely want, while
    a negative limit has no meaning the quota resolver could act on. The same
    rule and the same sentence apply to plan limits — see `plans.update_plan`.

    A new override does not revoke the old one for the same usage type. The
    resolver takes the most recently granted unexpired row, so a correction is
    a new grant, and the history of what was granted when survives it.
    """
    moment = now or dt.datetime.now(dt.UTC)
    if limit_value < 0:
        raise ValidationError("negative_limit").with_field(
            "limit_value", "The override limit must be a non-negative number."
        )
    if not reason.strip():
        raise ValidationError("reason_required_audited").with_field(
            "reason", "A reason is required."
        )
    if expires_at is not None and expires_at <= moment:
        raise ValidationError("override_expiry_in_past").with_field(
            "expires_at", "The effective period must end in the future."
        )

    override = QuotaOverride(
        override_id=uuid7(),
        tenant_id=tenant.tenant_id,
        usage_type=usage_type.value,
        limit_value=limit_value,
        reason=reason.strip(),
        granted_by=granted_by,
        granted_at=moment,
        expires_at=expires_at,
    )
    session.add(override)
    await session.flush()
    return override


__all__ = [
    "ASSIGNABLE_STATUSES",
    "MAX_LIMIT",
    "OverrideRow",
    "PlanSection",
    "Section",
    "StatusSection",
    "TenantDetail",
    "TenantPage",
    "TenantSummary",
    "UsageSection",
    "assign_plan",
    "change_status",
    "grant_override",
    "list_tenants",
    "require_tenant",
    "tenant_detail",
]
