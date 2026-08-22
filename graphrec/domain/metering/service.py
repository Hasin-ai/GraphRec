"""The three reads behind `/usage`: the rows, the trend, and the plan.

The console's usage page is one table of six rows, one trend panel of three
periods, and a kicker naming the plan (dc.html L1805-1824). This module answers
all three, and the discipline in every one of them is the same sentence from the
page's own subtitle: *"An unavailable measurement is stated, never shown as a
zero."*

That is why nothing here computes a fallback. A row's quantity is whatever
`sources.measure` returned, including `None`; a trend cell for a period that was
never rolled up is `None`; and `remaining` is `None` whenever either side of the
subtraction is unknown. There is no `or 0` in this file, and its absence is the
feature.

The other rule is that the current period and a closed one are read from
different places. The open period is measured live — the counter for accumulated
types, a live count for the catalogue — because it is still moving. A closed
period is read from `monthly_usage_aggregates`, because it has stopped moving
and because a point-in-time level like the product count has no history other
than the one the rollup wrote down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.enums import MEASUREMENT_STATUS_LABELS, MeasurementStatus, UsageType
from graphrec.domain import quotas
from graphrec.domain.metering import rollup, sources
from graphrec.domain.metering.periods import Period, current_period, recent_periods, trend_label

if TYPE_CHECKING:
    import datetime as dt
    import decimal
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.domain.metering.counters import UsageCounters

#: The trend panel's columns, after "Period" (L1818). Four of the six types:
#: storage and service capacity are not trended, because a level sampled once a
#: month is not a trend and the prototype does not claim otherwise.
TREND_TYPES: tuple[UsageType, ...] = (
    UsageType.EVENTS,
    UsageType.RECOMMENDATIONS,
    UsageType.TRAINING,
    UsageType.PRODUCTS,
)

#: L1824, verbatim. Rendered under the table whenever a row is not measured, so
#: the gap has a sentence rather than only a badge.
DELAYED_FOOTNOTE = (
    "Service capacity is measured continuously; the current reading is delayed, "
    "so remaining allowance is not calculable."
)


@dataclass(frozen=True, slots=True)
class UsageRow:
    """One row of the usage table (L1818)."""

    usage_type: UsageType
    measured: decimal.Decimal | None
    effective_limit: int | None
    remaining: int | None
    reset: str
    measurement_status: MeasurementStatus
    limit_source: quotas.LimitSource

    @property
    def status_label(self) -> str:
        """`measured` / `measurement delayed` / `unavailable` — the wire spelling
        the console tags with (BACKEND_PLAN L1190)."""
        return MEASUREMENT_STATUS_LABELS[self.measurement_status]


@dataclass(frozen=True, slots=True)
class UsageReport:
    period: Period
    items: list[UsageRow]

    @property
    def footnote(self) -> str | None:
        unmeasured = any(
            row.measurement_status is not MeasurementStatus.MEASURED for row in self.items
        )
        return DELAYED_FOOTNOTE if unmeasured else None


@dataclass(frozen=True, slots=True)
class TrendRow:
    period: Period
    label: str
    quantities: dict[UsageType, decimal.Decimal | None]


@dataclass(frozen=True, slots=True)
class Entitlement:
    usage_type: UsageType
    plan_limit: int | None
    effective_limit: int | None
    limit_source: quotas.LimitSource


@dataclass(frozen=True, slots=True)
class Subscription:
    plan_code: str
    plan_name: str
    description: str | None
    entitlements: list[Entitlement]


async def usage(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    now: dt.datetime,
) -> UsageReport:
    """All six rows for the current period."""
    period = current_period(now)
    rows: list[UsageRow] = []

    for usage_type in UsageType:
        measurement = await sources.measure(
            session, counters, tenant_id=tenant_id, usage_type=usage_type, period=period, live=True
        )
        limit = await quotas.resolve(session, tenant_id=tenant_id, usage_type=usage_type, now=now)
        rows.append(
            UsageRow(
                usage_type=usage_type,
                measured=measurement.quantity,
                effective_limit=limit.value,
                remaining=_remaining(measurement.quantity, limit.value),
                reset=sources.reset_label(usage_type, period=period),
                measurement_status=measurement.status,
                limit_source=limit.source,
            )
        )

    return UsageReport(period=period, items=rows)


async def trends(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    now: dt.datetime,
    periods: int = 3,
) -> list[TrendRow]:
    """The trend panel: three periods, newest first (L1818)."""
    current = current_period(now)
    rows: list[TrendRow] = []

    for period in recent_periods(now, count=periods):
        quantities: dict[UsageType, decimal.Decimal | None] = {}
        for usage_type in TREND_TYPES:
            if period == current:
                measurement = await sources.measure(
                    session,
                    counters,
                    tenant_id=tenant_id,
                    usage_type=usage_type,
                    period=period,
                    live=True,
                )
            else:
                # A closed period is whatever the rollup recorded. `None` when
                # it never ran — an unreconciled month is unmeasured, not empty.
                stored = await rollup.stored_measurement(
                    session, period=period, usage_type=usage_type
                )
                measurement = stored if stored is not None else sources.Measurement.delayed()
            quantities[usage_type] = measurement.quantity

        rows.append(
            TrendRow(
                period=period, label=trend_label(period, current=current), quantities=quantities
            )
        )

    return rows


async def subscription(
    session: AsyncSession, *, tenant_id: uuid.UUID, now: dt.datetime
) -> Subscription:
    """The plan and what it entitles the tenant to.

    Both limits are reported: the plan's figure and the one actually in force.
    The console's plan panel says "The plan sets the effective limits per usage
    type unless an approved override applies" (L1450), and a tenant looking at
    an override needs to see what it replaced — otherwise the override is
    invisible and the plan appears to be wrong.
    """
    row = (
        await session.execute(
            sa.text(
                "SELECT p.plan_code, p.plan_name, p.description, p.event_limit, "
                "       p.recommendation_limit, p.training_limit, p.product_limit, "
                "       p.storage_limit_bytes "
                "FROM pricing_plans AS p JOIN tenants AS t ON t.plan_id = p.plan_id "
                "WHERE t.tenant_id = :tenant_id"
            ),
            {"tenant_id": tenant_id},
        )
    ).one_or_none()

    if row is None:
        # A tenant with no plan is a provisioning fault, not a tenant-facing
        # error: every limit resolves as unbounded and the page still renders.
        plan_code, plan_name, description = "—", "—", None
        plan_limits: dict[UsageType, int | None] = dict.fromkeys(UsageType)
    else:
        plan_code, plan_name, description = row[0], row[1], row[2]
        plan_limits = {
            UsageType.EVENTS: row[3],
            UsageType.RECOMMENDATIONS: row[4],
            UsageType.TRAINING: row[5],
            UsageType.PRODUCTS: row[6],
            UsageType.STORAGE: row[7],
            UsageType.SERVICE_CAPACITY: None,
        }

    entitlements = []
    for usage_type in UsageType:
        limit = await quotas.resolve(session, tenant_id=tenant_id, usage_type=usage_type, now=now)
        plan_limit = plan_limits.get(usage_type)
        entitlements.append(
            Entitlement(
                usage_type=usage_type,
                plan_limit=None if plan_limit is None else int(plan_limit),
                effective_limit=limit.value,
                limit_source=limit.source,
            )
        )

    return Subscription(
        plan_code=str(plan_code),
        plan_name=str(plan_name),
        description=description,
        entitlements=entitlements,
    )


def _remaining(measured: decimal.Decimal | None, limit: int | None) -> int | None:
    """`None` unless both sides are known — the console's "not calculable"."""
    if measured is None or limit is None:
        return None
    return max(limit - int(measured), 0)


__all__ = [
    "DELAYED_FOOTNOTE",
    "TREND_TYPES",
    "Entitlement",
    "Subscription",
    "TrendRow",
    "UsageReport",
    "UsageRow",
    "subscription",
    "trends",
    "usage",
]
