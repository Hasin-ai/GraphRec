"""The fast counter, and the ledger it is never allowed to outrank.

BACKEND_PLAN L1840 asks that "the Redis fast counter reconciles to the durable
ledger". The tests here take the adversarial reading: not that the two agree
when nothing goes wrong, but that every way of pulling them apart — a cold
cache, an evicted key, a flush mid-period, a garbage value, an unreachable
server — resolves towards the ledger rather than towards zero.

`InMemoryUsageCounters` stands in for Redis. The adapter under test is the
`counter_ops.current` / `note_granted` protocol around it, which is the code
that would grant a tenant a free month if it treated a miss as a zero.
"""

from __future__ import annotations

import decimal

import pytest

from graphrec.common.enums import UsageType
from graphrec.domain.metering import counters as counter_ops
from graphrec.domain.metering import ledger, rollup
from graphrec.domain.metering.counters import (
    InMemoryUsageCounters,
    ResilientUsageCounters,
    counter_key,
)
from graphrec.domain.metering.periods import current_period
from tests.metering.conftest import NOW

pytestmark = [pytest.mark.db, pytest.mark.anyio]

PERIOD = current_period(NOW)


async def _grant(bound, tenant, key: str, quantity: int) -> None:
    async with bound(tenant) as session:
        await ledger.grant(
            session,
            tenant_id=tenant,
            usage_type=UsageType.EVENTS,
            quantity=quantity,
            idempotency_key=key,
            occurred_at=NOW,
        )


def _key(tenant) -> str:
    return counter_key(tenant_id=tenant, period=PERIOD, usage_type=UsageType.EVENTS)


# --------------------------------------------------------------- cold start


async def test_a_cold_counter_is_repaired_from_the_ledger(bound, counters, tenant) -> None:
    """The single most important behaviour in the module.

    Redis has never seen this tenant. If `current` answered zero, a tenant who
    had used their entire month's allowance would be handed it again on every
    deploy, restart or eviction.
    """
    await _grant(bound, tenant, "cold-start", 4_182)

    async with bound(tenant) as session:
        used = await counter_ops.current(
            session, counters, tenant_id=tenant, usage_type=UsageType.EVENTS, period=PERIOD
        )

    assert used == decimal.Decimal(4_182)


async def test_the_repair_seeds_the_key_so_it_is_paid_once(bound, counters, tenant) -> None:
    """A miss costs one `SUM`, not one per request.

    Without the seed the "fast" counter is a slow path wearing a cache's name,
    and the quota check on the ingest hot path sums a month of events per batch.
    """
    await _grant(bound, tenant, "seed-once", 12)
    assert await counters.read(_key(tenant)) is None

    async with bound(tenant) as session:
        await counter_ops.current(
            session, counters, tenant_id=tenant, usage_type=UsageType.EVENTS, period=PERIOD
        )

    assert await counters.read(_key(tenant)) == decimal.Decimal(12)


async def test_a_miss_reads_as_none_and_not_as_zero(counters) -> None:
    """The protocol's one non-obvious clause, asserted directly.

    Every caller distinguishes "no key" from "a key holding zero", and an
    adapter returning `0` for a miss would make that distinction unavailable at
    the boundary where it matters.
    """
    assert await counters.read("usage:nobody:2026-08:events") is None

    await counters.seed("usage:nobody:2026-08:events", decimal.Decimal(0))
    assert await counters.read("usage:nobody:2026-08:events") == decimal.Decimal(0)


# --------------------------------------------------------------- increments


async def test_a_granted_quantity_moves_the_counter(bound, counters, tenant) -> None:
    await _grant(bound, tenant, "warm", 100)
    async with bound(tenant) as session:
        await counter_ops.current(
            session, counters, tenant_id=tenant, usage_type=UsageType.EVENTS, period=PERIOD
        )

    await counter_ops.note_granted(
        counters, tenant_id=tenant, usage_type=UsageType.EVENTS, period=PERIOD, quantity=25
    )

    assert await counters.read(_key(tenant)) == decimal.Decimal(125)


async def test_an_increment_does_not_create_a_missing_key(counters, tenant) -> None:
    """`add` on an absent key is a no-op, deliberately (see `RedisUsageCounters`).

    Creating it would start the period at the size of one grant — a counter
    reading 25 for a tenant who has used four million, which is worse than no
    counter at all because `current` would believe it.
    """
    await counter_ops.note_granted(
        counters, tenant_id=tenant, usage_type=UsageType.EVENTS, period=PERIOD, quantity=25
    )
    assert await counters.read(_key(tenant)) is None


async def test_counters_are_keyed_per_tenant_type_and_period(tenant, ingest_tenants) -> None:
    """Three dimensions, all of them load-bearing.

    Sharing across any one of them mixes two tenants' bills, two allowances, or
    two months.
    """
    other = ingest_tenants["beta"]
    september = current_period(NOW.replace(month=9))

    keys = {
        counter_key(tenant_id=tenant, period=PERIOD, usage_type=UsageType.EVENTS),
        counter_key(tenant_id=other, period=PERIOD, usage_type=UsageType.EVENTS),
        counter_key(tenant_id=tenant, period=PERIOD, usage_type=UsageType.TRAINING),
        counter_key(tenant_id=tenant, period=september, usage_type=UsageType.EVENTS),
    }
    assert len(keys) == 4


# ------------------------------------------------------------ reconciliation


async def test_a_drifted_counter_is_corrected_by_the_rollup(bound, counters, tenant) -> None:
    """The stated criterion: the counter reconciles *to* the ledger.

    The drift is seeded in the direction that actually happens — a counter left
    high by a transaction that inserted its grant and then rolled back, or an
    increment applied twice by a retry. The rollup assigns rather than adjusts,
    so it lands on the ledger's figure regardless of how the counter got there.
    """
    await _grant(bound, tenant, "truth", 1_000)
    await counters.seed(_key(tenant), decimal.Decimal(9_999))

    async with bound(tenant) as session:
        await rollup.reconcile_period(session, counters, tenant_id=tenant, period=PERIOD, now=NOW)
        await session.commit()

    assert await counters.read(_key(tenant)) == decimal.Decimal(1_000)


async def test_reconciling_twice_lands_on_the_same_answer(bound, counters, tenant) -> None:
    """Idempotence is what makes the sweep safe to retry.

    A rollup that incremented would double a month's usage every time a
    scheduler fired twice, and a scheduler firing twice is a normal Tuesday.
    """
    await _grant(bound, tenant, "idempotent", 7)

    async with bound(tenant) as session:
        await rollup.reconcile_period(session, counters, tenant_id=tenant, period=PERIOD, now=NOW)
        await rollup.reconcile_period(session, counters, tenant_id=tenant, period=PERIOD, now=NOW)
        await session.commit()

    async with bound(tenant) as session:
        stored = await rollup.stored_measurement(
            session, period=PERIOD, usage_type=UsageType.EVENTS
        )
    assert stored is not None
    assert stored.quantity == decimal.Decimal(7)
    assert await counters.read(_key(tenant)) == decimal.Decimal(7)


async def test_a_closed_period_is_read_from_the_ledger_not_the_counter(
    bound, counters, tenant
) -> None:
    """Reconciliation must not trust the thing it is reconciling.

    `reconcile_period` passes `live=False`, so a counter holding a wrong number
    cannot launder that number into the aggregate — which would make the drift
    permanent and invisible.
    """
    await _grant(bound, tenant, "closed", 3)
    await counters.seed(_key(tenant), decimal.Decimal(500))

    async with bound(tenant) as session:
        measured = await rollup.reconcile_period(
            session, counters, tenant_id=tenant, period=PERIOD, now=NOW
        )

    assert measured[UsageType.EVENTS].quantity == decimal.Decimal(3)


# ------------------------------------------------------------- degraded cache


async def test_an_unreachable_cache_degrades_to_the_ledger(bound, tenant) -> None:
    """Redis down is slow, not wrong, and above all not free.

    The failing adapter raises on every call. The quota path must still get the
    tenant's real usage, because the alternative — a miss reported as zero —
    turns an infrastructure outage into an unmetered month.
    """
    await _grant(bound, tenant, "degraded", 88)
    broken = ResilientUsageCounters(_BrokenCounters())

    async with bound(tenant) as session:
        used = await counter_ops.current(
            session, broken, tenant_id=tenant, usage_type=UsageType.EVENTS, period=PERIOD
        )

    assert used == decimal.Decimal(88)


async def test_a_failing_seed_is_swallowed_rather_than_raised(caplog) -> None:
    """A cache write that fails must not fail the request that provoked it, and
    must not be silent either — the warning is how an unreachable Redis shows up
    as an operational fact rather than only as latency."""
    broken = ResilientUsageCounters(_BrokenCounters())

    with caplog.at_level("WARNING", logger="graphrec.metering.counters"):
        await broken.seed("usage:x:2026-08:events", decimal.Decimal(1))
        await broken.add("usage:x:2026-08:events", decimal.Decimal(1))

    assert [record.message for record in caplog.records] == [
        "usage_counter_seed_failed",
        "usage_counter_add_failed",
    ]


async def test_a_working_cache_is_passed_through_unharmed() -> None:
    """The resilient wrapper is a filter on failure, not on values."""
    resilient = ResilientUsageCounters(InMemoryUsageCounters())
    await resilient.seed("k", decimal.Decimal("1.5"))
    await resilient.add("k", decimal.Decimal("0.25"))
    assert await resilient.read("k") == decimal.Decimal("1.75")


class _BrokenCounters:
    """Every method raises, the way an unreachable Redis does."""

    async def read(self, key: str) -> decimal.Decimal | None:
        raise ConnectionError(key)

    async def seed(self, key: str, value: decimal.Decimal) -> None:
        raise ConnectionError(key)

    async def add(self, key: str, delta: decimal.Decimal) -> None:
        raise ConnectionError(key)
