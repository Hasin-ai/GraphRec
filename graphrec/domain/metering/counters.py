"""Fast counters, and the discipline that keeps them from becoming the truth.

Quota enforcement runs inside the transaction that creates a thing, so it runs
on every accepted event batch and — from Phase 11 — every recommendation
request. Answering "how much has this tenant used this month?" by summing
millions of ledger rows on that path is not viable, so the running total is
mirrored into Redis and read from there.

The whole design is one rule: **a counter may be fast or absent, never wrong in
the tenant's favour by accident.**

* A miss is not a zero. `current` recomputes from the ledger and seeds the key,
  so a cold, flushed or evicted Redis costs one slow query rather than granting
  a tenant unlimited usage.
* A counter is only incremented for a grant the ledger actually accepted, which
  is why `ledger.grant` returns a boolean.
* The increment happens next to the ledger insert, **inside** the caller's
  transaction — which Redis is not part of and cannot be rolled back with. A
  transaction that inserts the grant and then fails therefore leaves the counter
  high until the next reconciliation corrects it. That direction is chosen, not
  conceded: a counter that is high refuses a tenant slightly early, which is
  visible and appealable, while a counter that is low hands out allowance nobody
  recorded. The alternative — deferring the increment past the commit — would
  put a post-commit hook into the request plumbing of two auth realms to buy a
  correction the rollup already makes.
* Keys expire. A period's counter is worthless once the rollup has closed it,
  and a TTL means an abandoned tenant does not hold a key forever.

`InMemoryUsageCounters` is not a test double bolted on afterwards; it is the
adapter that lets the API run with no Redis at all. Metering degrades to "slow
but correct", which is the only degradation a measurement is allowed.
"""

from __future__ import annotations

import decimal
import logging
from typing import TYPE_CHECKING, Protocol

from graphrec.domain.metering import ledger
from graphrec.observability.metrics import METERING_DEGRADED

if TYPE_CHECKING:
    import uuid

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.common.enums import UsageType
    from graphrec.domain.metering.periods import Period

logger = logging.getLogger("graphrec.metering.counters")

#: Long enough that a closed period stays warm while the rollup runs, short
#: enough that nothing accumulates. A period is 31 days; 40 covers it with room.
COUNTER_TTL_SECONDS = 40 * 24 * 60 * 60


def counter_key(*, tenant_id: uuid.UUID, period: Period, usage_type: UsageType) -> str:
    """`usage:{tenant}:{period}:{type}` — tenant first, so a tenant's keys are
    contiguous and a tenant deletion can sweep them with one scan."""
    return f"usage:{tenant_id}:{period.label}:{usage_type.value}"


class UsageCounters(Protocol):
    """The port. Quantities cross it as strings.

    Redis counts in integers and this ledger counts in `numeric`; storage is
    measured in bytes and a future type may be fractional. Passing decimals as
    text and doing the arithmetic in Python keeps the adapter from quietly
    deciding what a quantity is.
    """

    async def read(self, key: str) -> decimal.Decimal | None:
        """The current value, or `None` if the key is absent. Never zero for a
        miss — the caller must be able to tell the two apart."""
        ...

    async def seed(self, key: str, value: decimal.Decimal) -> None: ...

    async def add(self, key: str, delta: decimal.Decimal) -> None: ...


class InMemoryUsageCounters:
    """Process-local counters. Correct, and not shared between replicas.

    Two API replicas each holding their own count would each let a tenant to the
    limit, so this adapter is for single-process runs and tests. `current` still
    recomputes from the ledger on a miss, so the failure mode is a limit
    overshoot proportional to replica count, not an unbounded one.
    """

    def __init__(self) -> None:
        self._values: dict[str, decimal.Decimal] = {}

    async def read(self, key: str) -> decimal.Decimal | None:
        return self._values.get(key)

    async def seed(self, key: str, value: decimal.Decimal) -> None:
        self._values[key] = value

    async def add(self, key: str, delta: decimal.Decimal) -> None:
        if key in self._values:
            self._values[key] += delta


class RedisUsageCounters:
    """The shared adapter.

    `add` uses `INCRBYFLOAT` on a key that must already exist, and deliberately
    does nothing when it does not. Creating the key here would start a period's
    count at the size of one grant rather than at the tenant's real total — a
    counter that says 40 when the tenant has used four million. A miss is left
    for `current` to repair from the ledger.
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def read(self, key: str) -> decimal.Decimal | None:
        raw = await self._client.get(key)
        if raw is None:
            return None
        try:
            return decimal.Decimal(raw.decode() if isinstance(raw, bytes) else str(raw))
        except decimal.InvalidOperation:
            # A key holding something that is not a number is a key we did not
            # write. Treat it as a miss and let the ledger overwrite it.
            return None

    async def seed(self, key: str, value: decimal.Decimal) -> None:
        await self._client.set(key, str(value), ex=COUNTER_TTL_SECONDS)

    async def add(self, key: str, delta: decimal.Decimal) -> None:
        if await self._client.exists(key):
            await self._client.incrbyfloat(key, float(delta))


class ResilientUsageCounters:
    """Any counters, with the cache's failures kept out of the tenant's way.

    This is where the module's rule stops being a comment and becomes code. If
    Redis is down, `read` reports a miss, `current` recomputes from the ledger,
    and the tenant gets the same number more slowly. A quota check does not fail
    because a cache is unreachable, and — more importantly — it does not *pass*
    because one is: a miss routes to the ledger, never to zero.

    `seed` and `add` swallow their errors for the same reason and with a
    different consequence: the counter is left stale, which the next
    reconciliation corrects. Both are logged at warning, once per failure, so an
    unreachable Redis is visible in operations rather than only in latency.

    And counted, not only logged. Degrading silently is how a cache stays broken
    for a week: every request still succeeds, every number is still right, and
    the only evidence is a ledger query per quota check that nobody is watching
    the latency of. `graphrec_metering_degraded_total` is the evidence.
    """

    def __init__(self, inner: UsageCounters) -> None:
        self._inner = inner

    async def read(self, key: str) -> decimal.Decimal | None:
        try:
            return await self._inner.read(key)
        except Exception:
            METERING_DEGRADED.inc()
            logger.warning("usage_counter_read_failed", extra={"key": key}, exc_info=True)
            return None

    async def seed(self, key: str, value: decimal.Decimal) -> None:
        try:
            await self._inner.seed(key, value)
        except Exception:
            METERING_DEGRADED.inc()
            logger.warning("usage_counter_seed_failed", extra={"key": key}, exc_info=True)

    async def add(self, key: str, delta: decimal.Decimal) -> None:
        try:
            await self._inner.add(key, delta)
        except Exception:
            METERING_DEGRADED.inc()
            logger.warning("usage_counter_add_failed", extra={"key": key}, exc_info=True)


async def current(
    session: AsyncSession,
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    usage_type: UsageType,
    period: Period,
) -> decimal.Decimal:
    """The tenant's usage so far this period — from the counter, or repaired.

    This is the function the quota check calls. On a hit it is one Redis read;
    on a miss it is one ledger sum followed by a seed, so the miss is paid once
    per period per replica rather than once per request.
    """
    key = counter_key(tenant_id=tenant_id, period=period, usage_type=usage_type)
    cached = await counters.read(key)
    if cached is not None:
        return cached

    total = await ledger.measured(session, usage_type=usage_type, period=period)
    await counters.seed(key, total)
    return total


async def note_granted(
    counters: UsageCounters,
    *,
    tenant_id: uuid.UUID,
    usage_type: UsageType,
    period: Period,
    quantity: decimal.Decimal | int,
) -> None:
    """Move the counter for a grant the ledger accepted.

    Called only when `ledger.grant` returned `True`, so a retried transaction
    re-inserting nothing also moves nothing.
    """
    await counters.add(
        counter_key(tenant_id=tenant_id, period=period, usage_type=usage_type),
        decimal.Decimal(quantity),
    )


__all__ = [
    "COUNTER_TTL_SECONDS",
    "InMemoryUsageCounters",
    "RedisUsageCounters",
    "ResilientUsageCounters",
    "UsageCounters",
    "counter_key",
    "current",
    "note_granted",
]
