"""The second exit criterion: a gap is a status, not a zero.

BUILD_PROMPT, step 7: "a delayed measurement renders as a status rather than a
zero." The tests here take that at three levels — the type that carries a
measurement, the row the rollup writes, and the response the console reads —
because a zero substituted at any one of them is the same lie to the tenant.

`storage` and `service_capacity` are the live examples rather than mocks. They
have no source until Phase 11, so the delay is real: these tests will keep
passing when Phase 11 lands a prober, and the assertions that would need editing
are exactly the ones that should be.
"""

from __future__ import annotations

import decimal

import pytest
import sqlalchemy as sa

from graphrec.common.enums import MEASUREMENT_STATUS_LABELS, MeasurementStatus, UsageType
from graphrec.domain.metering import rollup, service, sources
from graphrec.domain.metering.periods import current_period
from tests.metering.conftest import NOW

pytestmark = [pytest.mark.db, pytest.mark.anyio]


# ------------------------------------------ exit criterion: status, not zero


async def test_a_delayed_measurement_renders_as_a_status_rather_than_a_zero(
    bound, counters, tenant
) -> None:
    """The phase's stated exit criterion (BUILD_PROMPT, step 7).

    Storage has no prober before Phase 11. The row exists — the tenant sees the
    usage type — but its quantity is `None` and its status says why. A `0` here
    would tell a tenant they are storing nothing, which is a claim we have no
    evidence for.
    """
    async with bound(tenant) as session:
        report = await service.usage(session, counters, tenant_id=tenant, now=NOW)

    storage = _row(report, UsageType.STORAGE)
    assert storage.measured is None, "not zero — we did not measure it"
    assert storage.measurement_status is MeasurementStatus.DELAYED
    assert storage.status_label == "measurement delayed"


async def test_remaining_is_not_calculable_without_a_measurement(bound, counters, tenant) -> None:
    """A limit and no usage is still not an answer.

    Storage has a plan limit, so `limit - used` is one subtraction away — and
    the missing operand is the whole point. Reporting the full limit as
    remaining would be the same zero wearing the other side of the equation.
    """
    async with bound(tenant) as session:
        report = await service.usage(session, counters, tenant_id=tenant, now=NOW)

    storage = _row(report, UsageType.STORAGE)
    assert storage.effective_limit is not None, "the plan does bound storage"
    assert storage.remaining is None


async def test_the_page_carries_the_prototype_s_sentence_for_the_delay(
    bound, counters, tenant
) -> None:
    """The footnote is copy, not a badge (dc.html L1824).

    A status on a row tells a tenant that number is missing; the footnote tells
    them what it means for the allowance. Both, or the badge is a shrug.
    """
    async with bound(tenant) as session:
        report = await service.usage(session, counters, tenant_id=tenant, now=NOW)

    assert report.footnote == (
        "Service capacity is measured continuously; the current reading is delayed, "
        "so remaining allowance is not calculable."
    )


async def test_a_measured_row_is_a_number_and_carries_no_footnote(
    bound, counters, tenant, seed_products
) -> None:
    """The negative case, so the assertion above is not vacuous.

    Products *are* measurable, so that row is a quantity with a `measured`
    status — and a report of only measured rows has no footnote at all.
    """
    async with bound(tenant) as session:
        report = await service.usage(session, counters, tenant_id=tenant, now=NOW)

    products = _row(report, UsageType.PRODUCTS)
    assert products.measurement_status is MeasurementStatus.MEASURED
    assert products.measured is not None

    measured_only = service.UsageReport(
        period=report.period,
        items=[r for r in report.items if r.measurement_status is MeasurementStatus.MEASURED],
    )
    assert measured_only.footnote is None


async def test_zero_usage_is_measured_and_not_delayed(bound, counters, tenant) -> None:
    """The distinction runs both ways.

    A tenant who has sent no events this month has genuinely used zero, and
    saying "measurement delayed" there would be as wrong as saying zero for
    storage. `0` is an answer when we have one.
    """
    async with bound(tenant) as session:
        report = await service.usage(session, counters, tenant_id=tenant, now=NOW)

    events = _row(report, UsageType.EVENTS)
    assert events.measurement_status is MeasurementStatus.MEASURED
    assert events.measured == decimal.Decimal(0)


# -------------------------------------------------- the invariant, in Python


def test_a_status_and_a_quantity_cannot_disagree() -> None:
    """`Measurement` refuses the pair that the whole criterion is about.

    Not defensive programming: this is the invariant that lets every reader of a
    measurement trust `status` and `quantity` to say the same thing, so no view
    has to check both.
    """
    with pytest.raises(ValueError, match="cannot carry quantity"):
        sources.Measurement(decimal.Decimal(0), MeasurementStatus.DELAYED)

    with pytest.raises(ValueError, match="cannot carry quantity"):
        sources.Measurement(None, MeasurementStatus.MEASURED)


def test_every_status_has_a_label_the_console_renders() -> None:
    """A status with no copy would reach the page as an enum name."""
    for status in MeasurementStatus:
        assert MEASUREMENT_STATUS_LABELS[status]


def test_a_usage_type_with_no_source_is_delayed_by_construction() -> None:
    """The registry *is* the criterion (see `sources` module docstring).

    Storage and service capacity are absent from `MEASUREMENT_SOURCES`, and that
    absence is what produces the status. If a later phase adds an entry, this
    assertion fails and is meant to — it is the reminder to update the docs that
    say Phase 11 owns them.
    """
    unsourced = set(UsageType) - set(sources.MEASUREMENT_SOURCES)
    assert unsourced == {UsageType.STORAGE, UsageType.SERVICE_CAPACITY}


# ------------------------------------------------- the invariant, in Postgres


async def test_the_database_refuses_a_delayed_row_with_a_quantity(bound, tenant) -> None:
    """`ck_mua_measured_iff_quantity`, checked as the app role.

    The Python invariant guards this process; the check guards the table against
    a repair script, a psql session and every future phase.
    """
    period = current_period(NOW)
    async with bound(tenant) as session:
        with pytest.raises(sa.exc.IntegrityError):
            await session.execute(
                sa.text(
                    "INSERT INTO monthly_usage_aggregates "
                    "  (tenant_id, period_start, usage_type, quantity, measurement_status) "
                    "VALUES (:tid, :start, 'storage', 0, 'delayed')"
                ),
                {"tid": tenant, "start": period.start},
            )


async def test_the_database_refuses_a_measured_row_without_a_quantity(bound, tenant) -> None:
    """The other half. A `measured` NULL would render as a blank cell that
    claims to be a measurement."""
    period = current_period(NOW)
    async with bound(tenant) as session:
        with pytest.raises(sa.exc.IntegrityError):
            await session.execute(
                sa.text(
                    "INSERT INTO monthly_usage_aggregates "
                    "  (tenant_id, period_start, usage_type, quantity, measurement_status) "
                    "VALUES (:tid, :start, 'storage', NULL, 'measured')"
                ),
                {"tid": tenant, "start": period.start},
            )


# ---------------------------------------------------------- the rollup's row


async def test_the_rollup_writes_a_status_rather_than_a_zero(bound, counters, tenant) -> None:
    """Reconciliation faces the same temptation and declines it.

    A sweep over all six types could easily write `0` for the two it cannot
    measure, and the resulting row would be indistinguishable from a real zero
    forever after, because nothing downstream knows the difference.
    """
    period = current_period(NOW)
    async with bound(tenant) as session:
        await rollup.reconcile_period(session, counters, tenant_id=tenant, period=period, now=NOW)
        await session.commit()

    async with bound(tenant) as session:
        stored = await rollup.stored_measurement(
            session, period=period, usage_type=UsageType.STORAGE
        )

    assert stored is not None, "the row is written; only its quantity is missing"
    assert stored.quantity is None
    assert stored.status is MeasurementStatus.DELAYED


async def test_a_period_never_rolled_up_is_absent_rather_than_zero(bound, tenant) -> None:
    """`None` from `stored_measurement` is a third thing, distinct from both.

    "We never ran the rollup for July" is not "July was zero", and the caller —
    not the query — decides how to say so.
    """
    async with bound(tenant) as session:
        stored = await rollup.stored_measurement(
            session, period=current_period(NOW), usage_type=UsageType.EVENTS
        )
    assert stored is None


async def test_an_unreconciled_closed_period_trends_as_a_gap(bound, counters, tenant) -> None:
    """And the trend panel renders that gap as an empty cell.

    Three periods are shown; two of them precede this tenant's existence. A
    chart plotting those as zero would draw a usage cliff that never happened.
    """
    async with bound(tenant) as session:
        rows = await service.trends(session, counters, tenant_id=tenant, now=NOW)

    assert [row.label for row in rows] == ["2026-08 (current)", "2026-07", "2026-06"]
    assert rows[1].quantities[UsageType.EVENTS] is None
    assert rows[2].quantities[UsageType.EVENTS] is None
    # The open period is measured live, so it is a real zero.
    assert rows[0].quantities[UsageType.EVENTS] == decimal.Decimal(0)


def _row(report: service.UsageReport, usage_type: UsageType) -> service.UsageRow:
    return next(row for row in report.items if row.usage_type is usage_type)
