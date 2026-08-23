"""Cross-tenant usage, and the status board's refusal to invent numbers.

Two subjects, one theme: what the platform realm does when it does not know
something. Both answers are the same shape — say so, rather than showing a zero.

For **usage**, a tenant that does not exist is a `404` rather than an empty
page (L1524). An empty page reads as "that tenant used nothing", which is an
answer, and the operator settling a billing dispute would act on it.

For **status**, a quantity that could not be measured is `null` *and* named in
`measurement_gaps` with a sentence saying why. The distinction the board has to
preserve is between "zero requests failed" and "no requests were seen", which
look identical on a dashboard that renders both as `0`. `serving_availability`
has no denominator in a window with no traffic; `replicas.ready` is a mirror of
what the reconciler last wrote, so it goes stale rather than wrong.

Zero deployments, by contrast, is a *measured* zero and must not be reported as
a gap — the difference between "nothing is running" and "we cannot tell".
"""

from __future__ import annotations

import uuid

from tests.platform.conftest import auth

#: Every quantity the board can fail to measure, and therefore every key
#: `measurement_gaps` is allowed to name. Pinned so that adding a gap without
#: adding its copy fails here rather than rendering an empty tooltip.
GAP_QUANTITIES = {"serving_availability", "replicas", "ingestion_lag"}


def test_cross_tenant_usage_returns_aggregates_with_a_total(platform_api, full_operator) -> None:
    response = platform_api.get("/v1/platform/usage", headers=auth(full_operator))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"rows", "total", "limit", "offset"}
    for row in body["rows"]:
        assert set(row) >= {"tenant_id", "tenant_code", "period", "usage_type", "quantity"}


def test_naming_a_tenant_that_does_not_exist_is_a_404_not_an_empty_page(
    platform_api, full_operator
) -> None:
    """ "Rejected, not shown as an empty row" (L1524)."""
    response = platform_api.get(
        "/v1/platform/usage", headers=auth(full_operator), params={"tenant": str(uuid.uuid4())}
    )
    assert response.status_code == 404


def test_one_tenants_usage_lists_every_usage_type_even_the_unmeasured_ones(
    platform_api, full_operator, estate
) -> None:
    """A tenant that has never trained still has a training row, marked
    unavailable. Omitting the row would make "no training" and "training not
    measured" the same absence."""
    tenant_id = estate["tenants"]["acme"]["tenant_id"]
    response = platform_api.get(
        f"/v1/platform/tenants/{tenant_id}/usage", headers=auth(full_operator)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    types = {row["usage_type"] for row in body["rows"]}
    assert types == {
        "events",
        "recommendations",
        "training",
        "products",
        "storage",
        "service_capacity",
    }
    for row in body["rows"]:
        assert row["measurement_status"] in {"measured", "estimated", "unavailable"}


def test_the_status_board_reports_what_it_could_not_measure(platform_api, full_operator) -> None:
    """The exit criterion for the board: a null quantity is always explained."""
    response = platform_api.get("/v1/platform/status", headers=auth(full_operator))
    assert response.status_code == 200, response.text
    board = response.json()

    named = {gap["quantity"] for gap in board["measurement_gaps"]}
    assert named <= GAP_QUANTITIES, f"an unnamed gap: {named - GAP_QUANTITIES}"
    for gap in board["measurement_gaps"]:
        assert gap["reason"], f"{gap['quantity']} is a gap with no explanation"

    if board["serving_availability"] is None:
        assert "serving_availability" in named
    if board["replicas"]["ready"] is None:
        assert "replicas" in named


def test_a_quantity_that_was_measured_is_never_listed_as_a_gap(platform_api, full_operator) -> None:
    """The other direction, and the one that erodes trust in the board fastest:
    a dashboard that shows a number *and* says it could not be obtained."""
    board = platform_api.get("/v1/platform/status", headers=auth(full_operator)).json()
    named = {gap["quantity"] for gap in board["measurement_gaps"]}

    if board["serving_availability"] is not None:
        assert "serving_availability" not in named
    if board["replicas"]["ready"] is not None:
        assert "replicas" not in named
    if board["ingestion_lag_seconds"] is not None:
        assert "ingestion_lag" not in named


def test_an_idle_installation_reports_zero_rather_than_a_gap(platform_api, full_operator) -> None:
    """Counts are always measurable: nothing queued is a fact, not an absence."""
    board = platform_api.get("/v1/platform/status", headers=auth(full_operator)).json()
    assert board["training_queue"]["running"] >= 0
    assert board["training_queue"]["waiting"] >= 0
    assert board["training_queue"]["concurrency"] >= 1
    assert board["failures_24h"] >= 0
    assert board["active_tenants"] >= 1
    assert board["replicas"]["desired"] >= 0


def test_the_window_is_the_callers_and_is_reported_back(platform_api, full_operator) -> None:
    """`failures_24h` is named for the default, not for a fixed window; a board
    that silently ignored `window_hours` would answer a different question."""
    board = platform_api.get(
        "/v1/platform/status", headers=auth(full_operator), params={"window_hours": 1}
    ).json()
    assert board["window_hours"] == 1


def test_the_failures_list_redacts_the_tenant_unless_one_was_named(
    platform_api, full_operator, estate
) -> None:
    """A severity ranking must not double as a league table of which customers
    are struggling (L1550)."""
    unfiltered = platform_api.get("/v1/platform/failures", headers=auth(full_operator))
    assert unfiltered.status_code == 200, unfiltered.text
    assert all(row["tenant_id"] is None for row in unfiltered.json()["failures"])

    tenant_id = estate["tenants"]["acme"]["tenant_id"]
    filtered = platform_api.get(
        "/v1/platform/failures", headers=auth(full_operator), params={"tenant": str(tenant_id)}
    )
    assert filtered.status_code == 200, filtered.text
    assert all(row["tenant_id"] == str(tenant_id) for row in filtered.json()["failures"])
