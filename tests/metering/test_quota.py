"""Enforcement: the limit that applies, the usage against it, and the refusal.

Two obligations from BACKEND_PLAN L1840 — "override precedence over plan limit"
and "quota rejection names limit, usage and reset" — plus the structural one from
BUILD_PROMPT 7.5: the check runs inside the transaction that creates the thing it
guards.

The limits here are moved with `plan_limit` rather than reached by submitting six
million events. That is not a shortcut around the mechanism: `assert_within`
reads whatever `quotas.resolve` returns, so a plan bound of 10 exercises exactly
the comparison a bound of 10,000,000 would.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from graphrec.common.enums import UsageType
from graphrec.common.errors import ErrorClass, LimitError
from graphrec.domain import quotas
from graphrec.domain.metering import ledger
from graphrec.domain.metering import quota as usage_quota
from tests.metering.conftest import NOW

if TYPE_CHECKING:
    import decimal

pytestmark = [pytest.mark.db, pytest.mark.anyio]


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


# ------------------------------------------------------ which limit applies


async def test_an_override_takes_precedence_over_the_plan_limit(
    bound, tenant, plan_limit, grant_override
) -> None:
    """The stated obligation (BACKEND_PLAN L1840).

    An override exists to be *higher* than the plan, and the tenant was told to
    go and ask for one (L1603). If the plan still won, the platform would have
    granted something that changed nothing.
    """
    plan_limit(tenant, event_limit=10)
    grant_override(tenant, "events", 5_000)

    async with bound(tenant) as session:
        limit = await quotas.resolve(
            session, tenant_id=tenant, usage_type=UsageType.EVENTS, now=NOW
        )

    assert limit.value == 5_000
    assert limit.source == "override"


async def test_an_override_may_also_lower_a_limit(
    bound, tenant, plan_limit, grant_override
) -> None:
    """Precedence is precedence, not "the larger number wins".

    A `max()` would look kinder and would quietly make a deliberate throttle —
    an abuse response, a billing dispute — unenforceable.
    """
    plan_limit(tenant, event_limit=5_000)
    grant_override(tenant, "events", 10)

    async with bound(tenant) as session:
        limit = await quotas.resolve(
            session, tenant_id=tenant, usage_type=UsageType.EVENTS, now=NOW
        )

    assert limit.value == 10


async def test_a_revoked_override_falls_back_to_the_plan(
    bound, tenant, plan_limit, grant_override
) -> None:
    """Revocation has to actually revoke.

    An override row is kept for the audit trail rather than deleted, so
    `revoked_at` is the only thing standing between a withdrawn grant and a
    permanent one.
    """
    plan_limit(tenant, event_limit=10)
    grant_override(tenant, "events", 5_000, revoked_at=NOW - dt.timedelta(hours=1))

    async with bound(tenant) as session:
        limit = await quotas.resolve(
            session, tenant_id=tenant, usage_type=UsageType.EVENTS, now=NOW
        )

    assert limit.value == 10
    assert limit.source == "plan"


async def test_an_expired_override_falls_back_to_the_plan(
    bound, tenant, plan_limit, grant_override
) -> None:
    """A seasonal override is the common case — "approved for a seasonal peak"
    — and a peak that never ends is not a peak."""
    plan_limit(tenant, event_limit=10)
    grant_override(tenant, "events", 5_000, expires_at=NOW - dt.timedelta(days=1))

    async with bound(tenant) as session:
        limit = await quotas.resolve(
            session, tenant_id=tenant, usage_type=UsageType.EVENTS, now=NOW
        )

    assert limit.value == 10


async def test_an_override_for_another_usage_type_does_not_leak(
    bound, tenant, plan_limit, grant_override
) -> None:
    """More events is not more training runs.

    The two are priced differently and a shared lookup would let a cheap
    override buy an expensive resource.
    """
    plan_limit(tenant, event_limit=10, training_limit=2)
    grant_override(tenant, "events", 5_000)

    async with bound(tenant) as session:
        training = await quotas.resolve(
            session, tenant_id=tenant, usage_type=UsageType.TRAINING, now=NOW
        )

    assert training.value == 2
    assert training.source == "plan"


async def test_an_unbounded_type_resolves_to_no_limit(bound, tenant) -> None:
    """`service_capacity` has no plan column. `None` means "nothing to be within",
    and `assert_within` returns silently rather than comparing against zero."""
    async with bound(tenant) as session:
        limit = await quotas.resolve(
            session, tenant_id=tenant, usage_type=UsageType.SERVICE_CAPACITY, now=NOW
        )
        await usage_quota.assert_within(
            session,
            _NullCounters(),
            tenant_id=tenant,
            usage_type=UsageType.SERVICE_CAPACITY,
            requested=10**9,
            now=NOW,
        )

    assert limit.value is None


# -------------------------------------------------------------- the refusal


async def test_a_grant_that_fits_is_allowed(bound, counters, tenant, plan_limit) -> None:
    plan_limit(tenant, event_limit=100)
    await _grant(bound, tenant, "fits", 40)

    async with bound(tenant) as session:
        await usage_quota.assert_within(
            session,
            counters,
            tenant_id=tenant,
            usage_type=UsageType.EVENTS,
            requested=60,
            now=NOW,
        )


async def test_the_boundary_is_inclusive(bound, counters, tenant, plan_limit) -> None:
    """A limit of 100 permits the hundredth event and refuses the hundred and
    first. Off by one here is a tenant refused the allowance they paid for."""
    plan_limit(tenant, event_limit=100)
    await _grant(bound, tenant, "boundary", 99)

    async with bound(tenant) as session:
        await usage_quota.assert_within(
            session,
            counters,
            tenant_id=tenant,
            usage_type=UsageType.EVENTS,
            requested=1,
            now=NOW,
        )
        with pytest.raises(LimitError):
            await usage_quota.assert_within(
                session,
                counters,
                tenant_id=tenant,
                usage_type=UsageType.EVENTS,
                requested=2,
                now=NOW,
            )


async def test_the_rejection_names_limit_usage_and_reset(
    bound, counters, tenant, plan_limit
) -> None:
    """The stated obligation (BACKEND_PLAN L1840).

    "Quota exhausted" alone gives a tenant nothing to act on: they cannot tell
    whether they are marginally over or on the wrong plan, and the console has
    no numbers to render. The reset date is what makes waiting an option.
    """
    plan_limit(tenant, event_limit=1_000)
    await _grant(bound, tenant, "exhausted", 1_000)

    with pytest.raises(LimitError) as raised:
        async with bound(tenant) as session:
            await usage_quota.assert_within(
                session,
                counters,
                tenant_id=tenant,
                usage_type=UsageType.EVENTS,
                requested=1,
                now=NOW,
            )

    reason = raised.value.reason()
    assert "1,000 of 1,000 events" in reason, "usage and limit, thousands-separated"
    assert "2026-09-01" in reason, "the reset date"
    assert "quota override" in reason, "and what to do about it (L1603)"
    assert raised.value.error_class is ErrorClass.LIMIT
    assert raised.value.status_code == 429


async def test_the_rejection_names_the_plan_it_is_measured_against(
    bound, counters, tenant, plan_limit
) -> None:
    """ "on plan GROWTH" (L1603). A tenant reading a limit they do not recognise
    needs to know which plan produced it before they can argue with it."""
    plan_limit(tenant, event_limit=1)
    await _grant(bound, tenant, "named-plan", 1)

    with pytest.raises(LimitError) as raised:
        async with bound(tenant) as session:
            await usage_quota.assert_within(
                session,
                counters,
                tenant_id=tenant,
                usage_type=UsageType.EVENTS,
                requested=1,
                now=NOW,
            )

    async with bound(tenant) as session:
        code = await quotas.plan_code(session, tenant_id=tenant)
    assert f"on plan {code}" in raised.value.reason()


async def test_training_keeps_its_own_verbatim_sentence(
    bound, counters, tenant, plan_limit
) -> None:
    """The prototype writes training's refusal itself (L1647), and it names only
    the reset.

    The plan asks every rejection to name limit, usage and reset; approved copy
    outranks that, so the extra arguments are supplied and go unused rather than
    being appended to a sentence the prototype already settled. Recorded in the
    Phase 7 report rather than resolved by rewriting the copy.
    """
    plan_limit(tenant, training_limit=0)

    with pytest.raises(LimitError) as raised:
        async with bound(tenant) as session:
            await usage_quota.assert_within(
                session,
                counters,
                tenant_id=tenant,
                usage_type=UsageType.TRAINING,
                requested=1,
                now=NOW,
            )

    assert raised.value.reason() == (
        "The training quota for this period is exhausted. It resets on 2026-09-01."
    )


async def test_a_tenant_already_over_is_refused_before_doing_the_work(
    bound, counters, tenant, plan_limit
) -> None:
    """A `requested` of zero is still checked.

    The batch path asks before staging. Letting a zero-cost check through would
    move the refusal to after the parse and stage, which is the expensive half.
    """
    plan_limit(tenant, event_limit=10)
    await _grant(bound, tenant, "already-over", 11)

    with pytest.raises(LimitError):
        async with bound(tenant) as session:
            await usage_quota.assert_within(
                session,
                counters,
                tenant_id=tenant,
                usage_type=UsageType.EVENTS,
                requested=0,
                now=NOW,
            )


# --------------------------------------------------------------- remaining


async def test_remaining_is_never_negative(bound, counters, tenant, plan_limit) -> None:
    """A tenant over their limit has nothing left, not minus four thousand.

    Negative remaining reaches a progress bar as a negative width and a sentence
    as "-4,182 remaining", neither of which is a thing.
    """
    plan_limit(tenant, event_limit=10)
    await _grant(bound, tenant, "over", 4_192)

    async with bound(tenant) as session:
        left = await usage_quota.remaining(
            session, counters, tenant_id=tenant, usage_type=UsageType.EVENTS, now=NOW
        )

    assert left == 0


async def test_remaining_is_none_when_the_measurement_is_missing(bound, counters, tenant) -> None:
    """Storage has a limit and no prober, so the subtraction has one operand.

    This is the same criterion as `test_measurement`, asserted at the
    enforcement boundary: the code that decides whether to refuse must reach the
    same "not calculable" the page renders.
    """
    async with bound(tenant) as session:
        left = await usage_quota.remaining(
            session, counters, tenant_id=tenant, usage_type=UsageType.STORAGE, now=NOW
        )

    assert left is None


class _NullCounters:
    """Counters that would fail loudly if consulted.

    Used where the limit is `None`: `assert_within` must return before reading
    usage at all, because measuring what a tenant has used against no limit is
    work with no consumer.
    """

    async def read(self, key: str) -> decimal.Decimal | None:
        raise AssertionError("an unbounded type must not consult the counters")

    async def seed(self, key: str, value: decimal.Decimal) -> None:
        raise AssertionError("an unbounded type must not seed a counter")

    async def add(self, key: str, delta: decimal.Decimal) -> None:
        raise AssertionError("an unbounded type must not move a counter")
