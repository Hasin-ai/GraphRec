"""The board's gaps, asked about an instant of the test's own choosing.

The HTTP tests can only check that the board is *self-consistent* about whatever
the installation happens to look like when they run. This file picks the moment
instead, which is the only way to make a missing measurement certain rather than
likely: ask about a 24-hour window ending in 2099 and no request was served in
it, on any machine, ever.

The pair of assertions in each test is the point. A gap has to appear *and* the
quantity has to be null, because either alone is a worse failure than neither: a
null with no explanation is an unrendered dash, and an explanation next to a
number is a board nobody trusts twice.
"""

from __future__ import annotations

import datetime as dt

import pytest

from graphrec.common.error_copy import MEASUREMENT_GAP_COPY
from graphrec.domain import platform

#: Chosen so that every row in the database is unambiguously outside the window
#: and unambiguously older than the staleness bound.
LONG_AFTER = dt.datetime(2099, 1, 1, tzinfo=dt.UTC)

pytestmark = pytest.mark.db


async def test_a_window_with_no_requests_reports_availability_as_a_gap(
    platform_session,
) -> None:
    """No denominator, so no ratio — and not a zero, which would read as a
    total outage rather than as silence."""
    board = await platform.platform_status(platform_session, training_concurrency=2, now=LONG_AFTER)
    assert board.serving_availability is None
    gaps = {gap.quantity: gap.reason for gap in board.measurement_gaps}
    assert "serving_availability" in gaps
    assert gaps["serving_availability"] == MEASUREMENT_GAP_COPY["serving_availability"]


async def test_a_stale_replica_mirror_is_withheld_rather_than_rendered(
    platform_session,
) -> None:
    """`ready_replicas` is what the reconciler last wrote, not what is running.

    Both branches are asserted because both are correct answers to different
    installations: with deployments present the mirror has gone stale and `ready`
    must be withheld; with none present, zero of zero is a *measurement* and
    reporting a gap would be inventing an uncertainty.
    """
    board = await platform.platform_status(platform_session, training_concurrency=2, now=LONG_AFTER)
    gaps = {gap.quantity: gap.reason for gap in board.measurement_gaps}

    if board.replicas.desired or "replicas" in gaps:
        assert board.replicas.ready is None
        assert gaps["replicas"] == MEASUREMENT_GAP_COPY["replicas"]
    else:
        assert board.replicas.ready == 0
        assert board.replicas.desired == 0


async def test_counts_are_never_gaps(platform_session) -> None:
    """Queue depth, failures and tenants are rows that exist or do not.

    Asked about a window in which nothing happened, they are zero — a fact —
    and none of them may appear in `measurement_gaps`.
    """
    board = await platform.platform_status(platform_session, training_concurrency=3, now=LONG_AFTER)
    named = {gap.quantity for gap in board.measurement_gaps}
    assert "training_queue" not in named
    assert "failures" not in named
    assert "active_tenants" not in named
    assert board.failures_24h == 0
    assert board.training_queue.concurrency == 3


async def test_every_gap_reason_comes_from_the_copy_catalogue(platform_session) -> None:
    """The console renders these sentences verbatim, so none of them may be
    composed at the point of failure — see `graphrec/common/error_copy.py`."""
    board = await platform.platform_status(platform_session, training_concurrency=2, now=LONG_AFTER)
    for gap in board.measurement_gaps:
        assert gap.reason == MEASUREMENT_GAP_COPY[gap.quantity]
