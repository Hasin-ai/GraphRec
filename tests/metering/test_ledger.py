"""The ledger, and the two verbs it does not have.

BUILD_PROMPT's step-7 exit criterion is one sentence — "`UPDATE` on
`usage_events` raises" — and it is the first test here, with `DELETE` beside it
because a ledger you can empty is not more honest than one you can edit.

Everything connects as `graphrec_app`. That is the whole point: the constraint
being tested is a *grant*, and a grant is invisible to the migration owner, who
can rewrite any of these rows and would report a pass while the application
role's privileges said nothing at all.
"""

from __future__ import annotations

import datetime as dt
import decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError

from graphrec.common.enums import UsageType
from graphrec.domain.metering import ledger
from tests.metering.conftest import NOW

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _grant(bound, tenant, key: str, quantity: int = 10) -> None:
    async with bound(tenant) as session:
        await ledger.grant(
            session,
            tenant_id=tenant,
            usage_type=UsageType.EVENTS,
            quantity=quantity,
            idempotency_key=key,
            occurred_at=NOW,
        )


# ---------------------------------------------- exit criterion: immutability


async def test_update_on_usage_events_raises(bound, tenant) -> None:
    """The phase's stated exit criterion (BUILD_PROMPT, step 7).

    `graphrec_app` holds `SELECT, INSERT` and nothing else, so this is a
    privilege error rather than a trigger or a check — refused before the row is
    even located, and refused identically for every row including the tenant's
    own.
    """
    await _grant(bound, tenant, "ledger-update")

    with pytest.raises(ProgrammingError) as raised:
        async with bound(tenant) as session:
            await session.execute(sa.text("UPDATE usage_events SET quantity = 0"))

    assert "permission denied" in str(raised.value).lower()


async def test_delete_on_usage_events_raises(bound, tenant) -> None:
    """Not in the criterion, and refused anyway.

    An `UPDATE` grant would let a quantity be rewritten; a `DELETE` grant would
    let the row be removed and reinserted, which is the same edit with an extra
    step. Withholding one without the other would be a lock on the front door.
    """
    await _grant(bound, tenant, "ledger-delete")

    with pytest.raises(ProgrammingError) as raised:
        async with bound(tenant) as session:
            await session.execute(sa.text("DELETE FROM usage_events"))

    assert "permission denied" in str(raised.value).lower()


async def test_a_negative_quantity_is_refused(bound, tenant) -> None:
    """A correction is a later grant, never a negative one.

    Without this, everything the missing `UPDATE` grant prevents could be done
    by arithmetic instead: insert -4,182,400 and the month reads zero.
    """
    async with bound(tenant) as session:
        with pytest.raises(ValueError, match="non-negative"):
            await ledger.grant(
                session,
                tenant_id=tenant,
                usage_type=UsageType.EVENTS,
                quantity=-1,
                idempotency_key="ledger-negative",
                occurred_at=NOW,
            )


async def test_the_check_constraint_refuses_a_negative_quantity_too(bound, tenant) -> None:
    """The guard in `ledger.grant` is a better message, not the enforcement.

    A future caller writing SQL directly must hit the same wall, so the database
    holds the rule and the Python holds the explanation.
    """
    async with bound(tenant) as session:
        with pytest.raises(sa.exc.IntegrityError):
            await session.execute(
                sa.text(
                    "INSERT INTO usage_events (tenant_id, usage_type, quantity, "
                    "  idempotency_key, occurred_at) "
                    "VALUES (:tid, 'events', -1, 'raw-negative', :now)"
                ),
                {"tid": tenant, "now": NOW},
            )


# ------------------------------------------------------------- idempotency


async def test_the_same_idempotency_key_grants_once(bound, tenant) -> None:
    """A retried transaction re-attempts the grant; the ledger absorbs it.

    The boolean is the contract: `False` means "already recorded", and the
    caller uses it to leave the fast counter alone rather than to fail.
    """
    async with bound(tenant) as session:
        first = await ledger.grant(
            session,
            tenant_id=tenant,
            usage_type=UsageType.EVENTS,
            quantity=40,
            idempotency_key="submission:once",
            occurred_at=NOW,
        )
    async with bound(tenant) as session:
        second = await ledger.grant(
            session,
            tenant_id=tenant,
            usage_type=UsageType.EVENTS,
            quantity=40,
            idempotency_key="submission:once",
            occurred_at=NOW,
        )

    assert first is True
    assert second is False

    async with bound(tenant) as session:
        total = await ledger.measured(session, usage_type=UsageType.EVENTS, period=_august())
    assert total == decimal.Decimal(40), "the retry must not double-charge"


async def test_two_tenants_may_use_the_same_idempotency_key(bound, ingest_tenants) -> None:
    """The key is unique per tenant, not globally.

    `submission:<uuid>` happens not to collide, but `batch-001` does, and a
    tenant whose grant was silently swallowed because another tenant used the
    same word would be undercharged with no trace.
    """
    alpha, beta = ingest_tenants["alpha"], ingest_tenants["beta"]
    await _grant(bound, alpha, "batch-001", quantity=5)
    await _grant(bound, beta, "batch-001", quantity=7)

    async with bound(alpha) as session:
        assert await ledger.measured(
            session, usage_type=UsageType.EVENTS, period=_august()
        ) == decimal.Decimal(5)
    async with bound(beta) as session:
        assert await ledger.measured(
            session, usage_type=UsageType.EVENTS, period=_august()
        ) == decimal.Decimal(7)


# ------------------------------------------------------------------ periods


async def test_a_grant_lands_in_the_period_it_occurred_in(bound, tenant) -> None:
    """`occurred_at`, not `created_at`.

    A batch accepted at 23:59:58 on the 31st and written at 00:00:01 belongs to
    the month it was accepted in. Writing it into September would move a
    tenant's usage across a billing boundary because a worker was slow.
    """
    boundary = dt.datetime(2026, 8, 31, 23, 59, 58, tzinfo=dt.UTC)
    just_after = dt.datetime(2026, 9, 1, 0, 0, 0, tzinfo=dt.UTC)

    async with bound(tenant) as session:
        await ledger.grant(
            session,
            tenant_id=tenant,
            usage_type=UsageType.EVENTS,
            quantity=3,
            idempotency_key="august-tail",
            occurred_at=boundary,
        )
        await ledger.grant(
            session,
            tenant_id=tenant,
            usage_type=UsageType.EVENTS,
            quantity=11,
            idempotency_key="september-head",
            occurred_at=just_after,
        )

    async with bound(tenant) as session:
        august = await ledger.measured(session, usage_type=UsageType.EVENTS, period=_august())
        september = await ledger.measured(session, usage_type=UsageType.EVENTS, period=_september())

    # Half-open [start, end): midnight on the first belongs to September.
    assert august == decimal.Decimal(3)
    assert september == decimal.Decimal(11)


async def test_a_grant_is_invisible_to_another_tenant(bound, ingest_tenants) -> None:
    """RLS, on the ledger as everywhere else.

    Usage is a commercially sensitive number — how much a competitor's
    integration is doing is exactly what a shared table would leak.
    """
    alpha, beta = ingest_tenants["alpha"], ingest_tenants["beta"]
    await _grant(bound, alpha, "alpha-only", quantity=9)

    async with bound(beta) as session:
        assert await ledger.measured(
            session, usage_type=UsageType.EVENTS, period=_august()
        ) == decimal.Decimal(0)


def _august():
    from graphrec.domain.metering.periods import current_period

    return current_period(NOW)


def _september():
    from graphrec.domain.metering.periods import current_period

    return current_period(dt.datetime(2026, 9, 15, tzinfo=dt.UTC))
