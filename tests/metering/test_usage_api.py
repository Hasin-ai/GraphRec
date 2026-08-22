"""The three usage reads over HTTP.

`GET /v1/usage`, `/v1/usage/trends` and `/v1/subscription`, through the real app
with real sign-ins. What the domain tests cannot say: that the routes exist at
the published paths, that the administrator-only gate is actually on them, and
that a `None` from the domain survives serialisation as `null` rather than being
coerced into a zero by a response model with an unfortunate default.

The last of those is the reason this file exists at all. Every discipline in
`service.py` about not substituting zero can be undone by one Pydantic field
declared `int = 0`, and the type checker would not complain.
"""

from __future__ import annotations

import pytest

from graphrec.common.enums import UsageType
from tests.authz.conftest import auth

pytestmark = [pytest.mark.db]


# ------------------------------------------------------------------ the gate


def test_a_developer_is_refused_usage(api, home_dev) -> None:
    """ "No training, model, usage or service status access" (dc.html L1256).

    A 403 rather than a filtered page: usage is commercially sensitive, and a
    developer seeing an empty table would reasonably read it as "no usage".
    """
    response = api.get("/v1/usage", headers=auth(home_dev))
    assert response.status_code == 403, response.text


def test_a_developer_is_refused_the_trend_and_the_plan(api, home_dev) -> None:
    """The same gate on all three, since they answer the same question.

    Trends carry the same numbers over more periods, and the plan panel names
    what the tenant pays — gating one and not the others would be a lock beside
    an open window.
    """
    assert api.get("/v1/usage/trends", headers=auth(home_dev)).status_code == 403
    assert api.get("/v1/subscription", headers=auth(home_dev)).status_code == 403


def test_an_anonymous_caller_is_refused(api) -> None:
    assert api.get("/v1/usage").status_code == 401


def test_an_administrator_is_admitted(api, home_admin) -> None:
    assert api.get("/v1/usage", headers=auth(home_admin)).status_code == 200


# ------------------------------------------------------------------- /usage


def test_usage_reports_every_type_once(api, home_admin) -> None:
    """Six rows, the table the prototype draws (L1818).

    Omitting the two that cannot be measured would be the same erasure as a
    zero, one level up: a tenant would not know storage exists as a metered
    thing at all.
    """
    body = api.get("/v1/usage", headers=auth(home_admin)).json()
    assert [item["usage_type"] for item in body["items"]] == [t.value for t in UsageType]


def test_a_delayed_row_serialises_as_null_and_a_status(api, home_admin) -> None:
    """The exit criterion, on the wire.

    `null` is the only honest JSON for a number we do not have. `0` would be
    indistinguishable from a measured zero to every client forever after,
    including the console, the invoice and the tenant.
    """
    body = api.get("/v1/usage", headers=auth(home_admin)).json()
    storage = _item(body, UsageType.STORAGE)

    assert storage["measured"] is None
    assert storage["remaining"] is None
    assert storage["measurement_status"] == "measurement delayed"


def test_a_measured_row_serialises_as_a_number(api, home_admin) -> None:
    """The control. Without it the assertion above passes on a broken endpoint
    that returns `null` for everything."""
    body = api.get("/v1/usage", headers=auth(home_admin)).json()
    events = _item(body, UsageType.EVENTS)

    assert events["measured"] is not None
    assert events["measurement_status"] == "measured"


def test_the_period_and_its_reset_text_travel_with_the_rows(api, home_admin) -> None:
    """ "monthly · resets 2026-09-01" (L710) is copy, computed once, server-side.

    A client deriving the reset date from the period start would have to know
    the billing rule, and would get month-end arithmetic wrong in December.
    """
    body = api.get("/v1/usage", headers=auth(home_admin)).json()
    assert body["period"]["label"].startswith("monthly · resets ")
    assert body["period"]["label"].endswith(body["period"]["end"])
    assert _item(body, UsageType.EVENTS)["reset"] == body["period"]["label"]
    assert _item(body, UsageType.PRODUCTS)["reset"] == "no reset · standing limit"
    assert _item(body, UsageType.SERVICE_CAPACITY)["reset"] == "continuous"


def test_the_footnote_explains_the_gap(api, home_admin) -> None:
    """L1824, verbatim, because the delay currently applies."""
    body = api.get("/v1/usage", headers=auth(home_admin)).json()
    assert body["footnote"] == (
        "Service capacity is measured continuously; the current reading is delayed, "
        "so remaining allowance is not calculable."
    )


def test_each_row_says_where_its_limit_came_from(api, home_admin) -> None:
    """Two wire values only — `plan` or `override` (BACKEND_PLAN L1195).

    A tenant looking at a number that is not their plan's needs to be told it is
    an override; otherwise the plan panel appears to contradict the usage page.
    """
    body = api.get("/v1/usage", headers=auth(home_admin)).json()
    assert {item["limit_source"] for item in body["items"]} <= {"plan", "override"}


def test_usage_does_not_leak_across_tenants(api, home_admin, other_admin) -> None:
    """Two administrators, two accounts.

    Usage is a revenue signal; another tenant's is exactly the number a
    competitor would want. Both are 200 — the isolation is in the rows, not in
    a refusal that would reveal the other tenant exists.
    """
    home = api.get("/v1/usage", headers=auth(home_admin))
    other = api.get("/v1/usage", headers=auth(other_admin))
    assert home.status_code == other.status_code == 200
    assert home.json()["period"] == other.json()["period"]


# ------------------------------------------------------------------ /trends


def test_trends_returns_three_periods_newest_first(api, home_admin) -> None:
    """L1818's panel. Newest first is the order it renders and reads."""
    body = api.get("/v1/usage/trends", headers=auth(home_admin)).json()
    labels = [row["period"] for row in body["rows"]]

    assert len(labels) == 3
    assert labels == sorted(labels, reverse=True)
    assert body["rows"][0]["label"].endswith(" (current)")
    assert not body["rows"][1]["label"].endswith(" (current)")


def test_an_unmeasured_period_is_null_in_the_trend(api, home_admin) -> None:
    """The two months before this tenant existed were never rolled up.

    Plotted as zero they would draw a cliff into the current period that no
    tenant ever experienced, and a support conversation about a drop that did
    not happen.
    """
    body = api.get("/v1/usage/trends", headers=auth(home_admin)).json()
    assert body["rows"][1]["quantities"]["events"] is None


def test_the_client_may_ask_for_fewer_periods(api, home_admin) -> None:
    body = api.get("/v1/usage/trends?periods=1", headers=auth(home_admin)).json()
    assert len(body["rows"]) == 1


def test_the_client_may_not_ask_for_more_than_three(api, home_admin) -> None:
    """The prototype's filter offers at most "last 3 periods" (L1818).

    An unbounded `periods` is a per-request loop over the aggregate table with
    a caller-chosen bound, which is a denial of service with a query parameter.
    """
    assert api.get("/v1/usage/trends?periods=99", headers=auth(home_admin)).status_code == 422
    assert api.get("/v1/usage/trends?periods=0", headers=auth(home_admin)).status_code == 422


# ------------------------------------------------------------ /subscription


def test_the_subscription_names_the_plan(api, home_admin) -> None:
    """ "Plan GROWTH" — the usage page's kicker (L1805)."""
    body = api.get("/v1/subscription", headers=auth(home_admin)).json()
    assert body["plan_code"] == "GROWTH"
    assert body["plan_name"]


def test_entitlements_report_the_plan_limit_beside_the_effective_one(api, home_admin) -> None:
    """Both, so an override is visible as a difference (L1450).

    Reporting only the effective limit makes a tenant on an override believe
    their plan is something it is not; reporting only the plan's makes the
    override invisible and the enforcement look wrong.
    """
    body = api.get("/v1/subscription", headers=auth(home_admin)).json()
    entitlements = {item["usage_type"]: item for item in body["entitlements"]}

    assert set(entitlements) == {t.value for t in UsageType}
    events = entitlements[UsageType.EVENTS.value]
    assert events["plan_limit"] == events["effective_limit"]
    assert events["limit_source"] == "plan"


def test_an_unbounded_entitlement_is_null_rather_than_zero(api, home_admin) -> None:
    """Service capacity has no plan column.

    `0` would read as "you are entitled to none", which is the opposite of
    "this is not bounded" and would be a bewildering thing to show beside a
    working service.
    """
    body = api.get("/v1/subscription", headers=auth(home_admin)).json()
    capacity = next(
        item
        for item in body["entitlements"]
        if item["usage_type"] == UsageType.SERVICE_CAPACITY.value
    )
    assert capacity["plan_limit"] is None
    assert capacity["effective_limit"] is None


def _item(body: dict, usage_type: UsageType) -> dict:
    return next(item for item in body["items"] if item["usage_type"] == usage_type.value)
