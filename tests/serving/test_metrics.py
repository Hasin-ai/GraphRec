"""What the console is told about a tenant's serving, and what it is not.

Two rules run through all of it.

**A window with no traffic is `delayed`, never zero.** BACKEND_PLAN L1200: a
measurement that is missing is reported as missing. `availability: 0.0` on a
quiet night would page somebody; `availability: 1.0` would be a number nobody
measured. `None` with a status beside it is the only honest pair.

**An error panel renders a closed set and approved copy.** dc.html L1842:
"Error classes only. Request payloads and recommendation results are never
rendered here." So the tests below put a caller's string into the row and check
it cannot come back out.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from graphrec.common.enums import MeasurementStatus
from graphrec.domain.serving.metrics import MetricsService, reference_for
from graphrec.serving.states import ServingErrorClass

pytestmark = [pytest.mark.db]

SERVICE = MetricsService()


# ---------------------------------------------------------------- summary


async def test_a_window_with_no_traffic_is_delayed_rather_than_zero(
    serving_tenants, bound_serving
) -> None:
    tenant_id = serving_tenants["alpha"]

    async with bound_serving(tenant_id) as session:
        metrics = await SERVICE.summary(session)

    assert metrics.status is MeasurementStatus.DELAYED
    assert metrics.requests == 0
    assert metrics.availability is None
    assert metrics.latency_p95_ms is None
    assert metrics.fallback_rate is None
    assert metrics.freshness_seconds is None


async def test_traffic_outside_the_window_does_not_make_it_measured(
    serving_tenants, seed_requests, bound_serving
) -> None:
    """Yesterday's requests are not evidence about today.

    A summary that reached back for the last row it could find would report a
    24-hour availability computed from a week-old sample, and the number would
    look like a measurement.
    """
    tenant_id = serving_tenants["alpha"]
    seed_requests(tenant_id, count=50, age=dt.timedelta(days=3))

    async with bound_serving(tenant_id) as session:
        metrics = await SERVICE.summary(session)

    assert metrics.status is MeasurementStatus.DELAYED
    assert metrics.requests == 0


async def test_availability_counts_refusals_and_not_degradations(
    serving_tenants, seed_requests, bound_serving
) -> None:
    """A fallback answer was an answer.

    Folding degradations into availability would make a model outage look like
    a platform outage, and the tenant would not be able to tell from the number
    whether their shop had stopped recommending or stopped responding. They are
    drawn as separate stats (dc.html L1831, L1837) because they are separate
    failures.
    """
    tenant_id = serving_tenants["alpha"]
    seed_requests(tenant_id, count=90, status="served")
    seed_requests(tenant_id, count=5, status="degraded", fallback=True, prefix="d")
    seed_requests(tenant_id, count=5, status="refused", latency_ms=None, prefix="r")

    async with bound_serving(tenant_id) as session:
        metrics = await SERVICE.summary(session)

    assert metrics.status is MeasurementStatus.MEASURED
    assert metrics.requests == 100
    assert metrics.availability == pytest.approx(0.95)
    # Both the degraded and the refused rows are errors; only the refusals are
    # unavailability.
    assert metrics.errors == 10
    assert metrics.fallback_rate == pytest.approx(0.05)


async def test_the_p95_is_a_percentile_and_not_a_mean(
    serving_tenants, seed_requests, bound_serving
) -> None:
    """Ninety requests at 10 ms and ten at 1,000.

    The mean is 109 ms — a figure describing a service nobody experienced,
    since every request was either fast or very slow. The 95th percentile lands
    in the slow tail, which is where one request in twenty actually was, and is
    the number NR-NF-04 is written about.
    """
    tenant_id = serving_tenants["alpha"]
    seed_requests(tenant_id, count=90, latency_ms=10)
    seed_requests(tenant_id, count=10, latency_ms=1000, prefix="slow")

    async with bound_serving(tenant_id) as session:
        metrics = await SERVICE.summary(session)

    assert metrics.latency_p95_ms == 1000


async def test_freshness_is_the_age_of_the_data_and_not_of_the_query(
    serving_tenants, seed_requests, bound_serving
) -> None:
    """dc.html L1839 draws "12 s ago". A board refreshed every second over an
    hour-old row is stale, and reporting the query's own age would hide it."""
    tenant_id = serving_tenants["alpha"]
    seed_requests(tenant_id, count=3, age=dt.timedelta(hours=2))

    async with bound_serving(tenant_id) as session:
        metrics = await SERVICE.summary(session)

    assert metrics.freshness_seconds is not None
    assert metrics.freshness_seconds >= 2 * 60 * 60


async def test_one_tenants_traffic_is_never_counted_in_anothers_summary(
    serving_tenants, seed_requests, bound_serving
) -> None:
    tenant_id, other = serving_tenants["alpha"], serving_tenants["beta"]
    seed_requests(tenant_id, count=10)
    seed_requests(other, count=40, status="refused", latency_ms=None)

    async with bound_serving(tenant_id) as session:
        mine = await SERVICE.summary(session)
    async with bound_serving(other) as session:
        theirs = await SERVICE.summary(session)

    assert mine.requests == 10
    assert mine.availability == 1.0
    assert theirs.requests == 40
    assert theirs.availability == 0.0


async def test_a_narrower_window_reports_the_narrower_window(
    serving_tenants, seed_requests, bound_serving
) -> None:
    """The console offers 24 hours, 7 days and 30 days (L1830), and the window
    is echoed back so a chart cannot mislabel its own axis."""
    tenant_id = serving_tenants["alpha"]
    seed_requests(tenant_id, count=4, age=dt.timedelta(minutes=10))
    seed_requests(tenant_id, count=6, age=dt.timedelta(hours=6), prefix="old")

    async with bound_serving(tenant_id) as session:
        hour = await SERVICE.summary(session, window=dt.timedelta(hours=1))
        day = await SERVICE.summary(session)

    assert hour.requests == 4
    assert hour.window_hours == 1
    assert day.requests == 10
    assert day.window_hours == 24


# ----------------------------------------------------------------- errors


async def test_the_error_panel_renders_only_closed_enum_classes(
    serving_tenants, seed_requests, bound_serving
) -> None:
    tenant_id = serving_tenants["alpha"]
    for error_class in ServingErrorClass:
        seed_requests(
            tenant_id,
            status="refused",
            latency_ms=None,
            error_class=error_class.value,
            error_reason="The recommendation service is temporarily unavailable.",
            prefix=error_class.value,
        )

    async with bound_serving(tenant_id) as session:
        errors = await SERVICE.errors(session)

    assert {error.error_class for error in errors} == set(ServingErrorClass)
    assert all(isinstance(error.error_class, ServingErrorClass) for error in errors)


async def test_a_successful_request_never_appears_in_the_error_panel(
    serving_tenants, seed_requests, bound_serving
) -> None:
    tenant_id = serving_tenants["alpha"]
    seed_requests(tenant_id, count=20, status="served")
    seed_requests(
        tenant_id,
        status="refused",
        latency_ms=None,
        error_class=ServingErrorClass.UNAVAILABLE.value,
        error_reason="The recommendation service is temporarily unavailable.",
        prefix="bad",
    )

    async with bound_serving(tenant_id) as session:
        errors = await SERVICE.errors(session)

    assert len(errors) == 1


async def test_the_panel_is_newest_first_and_bounded(
    serving_tenants, seed_requests, bound_serving
) -> None:
    """A panel with no pagination control must not depend on how much went
    wrong. Twenty rows is enough to see a pattern in."""
    tenant_id = serving_tenants["alpha"]
    seed_requests(
        tenant_id,
        count=40,
        status="refused",
        latency_ms=None,
        error_class=ServingErrorClass.INTERNAL.value,
        error_reason="Something went wrong on our side.",
    )

    async with bound_serving(tenant_id) as session:
        errors = await SERVICE.errors(session)

    assert len(errors) == 20
    assert [error.occurred_at for error in errors] == sorted(
        (error.occurred_at for error in errors), reverse=True
    )


async def test_one_tenants_failures_are_invisible_to_another(
    serving_tenants, seed_requests, bound_serving
) -> None:
    """The failures of a competitor sharing this platform are not a thing a
    tenant may observe, including by counting them."""
    tenant_id, other = serving_tenants["alpha"], serving_tenants["beta"]
    seed_requests(
        other,
        count=5,
        status="refused",
        latency_ms=None,
        error_class=ServingErrorClass.INTERNAL.value,
        error_reason="Something went wrong on our side.",
    )

    async with bound_serving(tenant_id) as session:
        errors = await SERVICE.errors(session)

    assert errors == []


async def test_the_reference_is_a_short_handle_and_not_the_row_key(
    serving_tenants, bound_serving
) -> None:
    """`err-3f81`. Four hex characters is not unique and is not meant to be: it
    is something to say out loud in a support conversation, and it does not
    address the row it came from."""
    request_id = uuid.UUID("3f81a2b4-0000-4000-8000-000000000001")

    reference = reference_for(request_id)

    assert reference == "err-3f81"
    assert str(request_id) not in reference
