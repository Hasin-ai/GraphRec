"""Reconciliation: recomputing the account from the ledger.

The rollup exists because there are two derived copies of a number that must not
be allowed to drift from the ledger — the Redis counter and the monthly
aggregate — and drift is not a hypothetical. Redis restarts. A grant commits
while the process incrementing the counter is killed between the commit and the
`INCRBYFLOAT`. A period ends and its running total has to become a fixed
historical fact.

So this recomputes both from `usage_events`, which is the only copy that cannot
have been edited. Recomputing from an immutable source is the property that
makes the rollup safe to run twice, out of order, or after a crash — it is not
an increment, it is an assignment, so running it again lands on the same answer.

Two things it deliberately does not do:

* It does not write a zero for a type it cannot measure. A period with no
  storage prober gets a row with `quantity NULL` and status `delayed`, and the
  console renders "measurement delayed" (dc.html L715). Writing zero would turn
  "we did not measure" into "there was none", which is the exact substitution
  BUILD_PROMPT's step-7 criterion forbids.
* It does not delete or revise the ledger to match. If the aggregate and the
  ledger disagree, the ledger is right; there is no grant that would let this
  code decide otherwise, which is the point of the missing `UPDATE`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.enums import MeasurementStatus, UsageType
from graphrec.domain.metering import counters as counter_ops
from graphrec.domain.metering import sources
from graphrec.domain.metering.periods import Period, current_period, recent_periods

if TYPE_CHECKING:
    import datetime as dt
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.domain.metering.counters import UsageCounters


async def reconcile_period(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    period: Period,
    now: dt.datetime,
) -> dict[UsageType, sources.Measurement]:
    """Recompute one tenant's period, upsert the aggregates, reseed the counters.

    Runs in the caller's transaction against a tenant-bound session, so every
    read and write is inside the tenant's own RLS policy.
    """
    live = period == current_period(now)
    measured: dict[UsageType, sources.Measurement] = {}

    for usage_type in UsageType:
        measurement = await sources.measure(
            session,
            counters,
            tenant_id=tenant_id,
            usage_type=usage_type,
            period=period,
            # A rollup always recomputes from the durable source: passing
            # `live=False` for an accumulated type reads the ledger rather than
            # the counter, which is the whole point of reconciling.
            live=False,
        )
        measured[usage_type] = measurement
        await _upsert(
            session,
            tenant_id=tenant_id,
            period=period,
            usage_type=usage_type,
            measurement=measurement,
            now=now,
        )

    if live:
        # Only the open period has counters worth correcting. Seeding, not
        # adding: the ledger total replaces whatever the counter had drifted to.
        for usage_type in sources.ACCUMULATED_TYPES:
            measurement = measured[usage_type]
            if measurement.quantity is None:
                continue
            await counters.seed(
                counter_ops.counter_key(tenant_id=tenant_id, period=period, usage_type=usage_type),
                measurement.quantity,
            )

    return measured


async def reconcile_recent(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    now: dt.datetime,
    periods: int = 2,
) -> None:
    """The scheduled sweep: the open period and the one that just closed.

    Two by default, because a rollup running at 00:03 on the first of the month
    has an open period with almost nothing in it and a closed period that has
    just stopped changing. Recomputing only the current one would leave the
    previous month permanently holding whatever partial figure it had at the
    last sweep before midnight.
    """
    for period in recent_periods(now, count=periods):
        await reconcile_period(session, counters, tenant_id=tenant_id, period=period, now=now)


async def _upsert(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    period: Period,
    usage_type: UsageType,
    measurement: sources.Measurement,
    now: dt.datetime,
) -> None:
    """Assignment, not increment. See the module docstring."""
    await session.execute(
        sa.text(
            "INSERT INTO monthly_usage_aggregates "
            "  (tenant_id, period_start, usage_type, quantity, measurement_status, "
            "   computed_at, created_at, updated_at) "
            "VALUES (:tenant_id, :period_start, :usage_type, :quantity, :status, "
            "        :now, :now, :now) "
            "ON CONFLICT (tenant_id, period_start, usage_type) DO UPDATE SET "
            "  quantity = EXCLUDED.quantity, "
            "  measurement_status = EXCLUDED.measurement_status, "
            "  computed_at = EXCLUDED.computed_at, "
            "  updated_at = EXCLUDED.updated_at"
        ),
        {
            "tenant_id": tenant_id,
            "period_start": period.start,
            "usage_type": usage_type.value,
            "quantity": measurement.quantity,
            "status": measurement.status.value,
            "now": now,
        },
    )


async def stored_measurement(
    session: AsyncSession, *, period: Period, usage_type: UsageType
) -> sources.Measurement | None:
    """What the last rollup recorded, or `None` if it never ran for this period.

    `None` is not zero and is not a status. The caller decides what an
    unreconciled period means — `service.py` reports it as `delayed`, because a
    period we have never rolled up is a period we have not measured.
    """
    row = (
        await session.execute(
            sa.text(
                "SELECT quantity, measurement_status FROM monthly_usage_aggregates "
                "WHERE period_start = :period_start AND usage_type = :usage_type"
            ),
            {"period_start": period.start, "usage_type": usage_type.value},
        )
    ).one_or_none()
    if row is None:
        return None
    quantity, status = row
    return sources.Measurement(quantity, MeasurementStatus(status))


__all__ = ["reconcile_period", "reconcile_recent", "stored_measurement"]
