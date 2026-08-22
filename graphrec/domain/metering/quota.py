"""The usage half of a quota: what has been used, against what is allowed.

`graphrec.domain.quotas` resolves the *limit*. This resolves the *usage* and
puts the two together, which is the only place in the system that decides a
tenant has run out.

Three properties it is responsible for.

**It runs inside the creating transaction** (BUILD_PROMPT 7.5). The check and
the insert it guards share a transaction, so the count the check took is the
count the insert is measured against. `READ COMMITTED` still lets two concurrent
creates both pass at the boundary — the same one-item overshoot Phase 5 accepted
for products, for the same reason: serialising every metered write behind a lock
would cost far more than the overshoot it prevents.

**It reads the fast counter, not the ledger.** A `SUM` over a month of events on
every accepted batch is not viable, so `counters.current` answers — and repairs
itself from the ledger on a miss, so a cold Redis costs a query rather than a
free month.

**Its refusal names the numbers** (BACKEND_PLAN L1840: "quota rejection names
limit, usage and reset"). A 429 that says only "quota exhausted" leaves a tenant
with no way to tell whether they are marginally over or need a different plan,
and the console has nothing to render but the bare sentence. The numbers travel
in the approved copy, as they do for products (L1603) — the error envelope has
no `details` object and this phase is not the place to invent one.
"""

from __future__ import annotations

import decimal
from typing import TYPE_CHECKING

from graphrec.common.enums import UsageType
from graphrec.common.errors import LimitError
from graphrec.domain import quotas
from graphrec.domain.metering import counters as counter_ops
from graphrec.domain.metering import sources
from graphrec.domain.metering.periods import current_period

if TYPE_CHECKING:
    import datetime as dt
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.domain.metering.counters import UsageCounters

#: The copy key each accumulated type refuses with. Separate keys rather than
#: one generic string because the prototype gives training its own sentence
#: (L1647) and the register differs: a tenant out of *events* has a period to
#: wait for, a tenant out of *training runs* has a job to not start.
QUOTA_COPY: dict[UsageType, str] = {
    UsageType.EVENTS: "event_quota_exhausted",
    UsageType.RECOMMENDATIONS: "recommendation_quota_exhausted",
    UsageType.TRAINING: "training_quota_exhausted",
}


async def assert_within(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    usage_type: UsageType,
    requested: decimal.Decimal | int,
    now: dt.datetime,
) -> None:
    """Raise `LimitError` if granting `requested` would exceed the limit.

    Returns silently when the type is unbounded, when no limit is configured, or
    when the grant fits. A `requested` of zero is still checked: a tenant already
    over their limit should be refused before doing more work, not after.
    """
    limit = await quotas.resolve(session, tenant_id=tenant_id, usage_type=usage_type, now=now)
    if limit.value is None:
        return

    period = current_period(now)
    used = await counter_ops.current(
        session, counters, tenant_id=tenant_id, usage_type=usage_type, period=period
    )
    wanted = decimal.Decimal(requested)
    if used + wanted <= limit.value:
        return

    raise LimitError(
        QUOTA_COPY.get(usage_type, "usage_quota_exhausted"),
        copy_args={
            "used": f"{int(used):,}",
            "limit": f"{limit.value:,}",
            "requested": f"{int(wanted):,}",
            "resets_on": period.end.isoformat(),
            "plan_code": await quotas.plan_code(session, tenant_id=tenant_id),
        },
    )


async def remaining(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    usage_type: UsageType,
    now: dt.datetime,
) -> int | None:
    """How much allowance is left, or `None` when that is not calculable.

    `None` for an unbounded type, and `None` when the measurement is missing —
    the console's "not calculable" (dc.html L715). Never a negative: a tenant
    over their limit has nothing left, not minus four thousand.
    """
    limit = await quotas.resolve(session, tenant_id=tenant_id, usage_type=usage_type, now=now)
    if limit.value is None:
        return None

    period = current_period(now)
    measurement = await sources.measure(
        session, counters, tenant_id=tenant_id, usage_type=usage_type, period=period, live=True
    )
    if measurement.quantity is None:
        return None
    return max(limit.value - int(measurement.quantity), 0)


__all__ = ["QUOTA_COPY", "assert_within", "remaining"]
