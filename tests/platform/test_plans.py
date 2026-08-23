"""The price list: creating a plan, editing it, and closing it to new joiners.

Closing is the interesting one, and the tests below spend most of their length
on it, because "closed" has a precise meaning that a plausible implementation
gets wrong in both directions. Closing a plan does *not* evict its tenants and
does *not* leave them unpriced (L1496); it refuses **new** assignments only. So
a tenant already on a closed plan can be re-assigned to it — a re-save from the
console must not fail — while a tenant on some other plan cannot join.

Plan limits are not versioned. A tenant's bounds come from whatever the plan
says now, which means editing a plan silently re-prices every tenant on it, and
the audit row carrying the new figures is the only record the old ones existed.
That is a deliberate simplification and it is asserted here so that changing it
requires changing a test that explains why.
"""

from __future__ import annotations

import uuid

import pytest

from tests.isolation.conftest import _force_lifted
from tests.platform.conftest import auth

LIMITS = {
    "event_limit": 1_000_000,
    "recommendation_limit": 500_000,
    "training_limit": 20,
    "product_limit": 100_000,
    "storage_limit_bytes": 10_000_000_000,
}


@pytest.fixture
def a_plan(platform_api, full_operator, owner_engine):
    """A plan of this test's own, torn down afterwards.

    Nothing here edits the seeded plans: they are what every other suite's
    tenants are priced against, and a test that lowered `GROWTH`'s event limit
    would fail the metering suite in a way nobody would connect back to here.
    """
    import sqlalchemy as sa

    code = f"TEST{uuid.uuid4().hex[:6].upper()}"
    response = platform_api.post(
        "/v1/platform/plans",
        headers=auth(full_operator),
        json={"plan_code": code, "plan_name": "A Test Plan", "limits": LIMITS},
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    yield plan
    # `tenant_subscriptions` is `FORCE`d and no policy names the owner, so an
    # owner DELETE matches nothing and reports success — and the plan delete
    # below then fails its foreign key. Lift, delete, restore, which is the
    # procedure migration 0002 documents for teardown and nowhere else.
    with owner_engine.begin() as conn, _force_lifted(conn, "tenant_subscriptions"):
        conn.execute(
            sa.text("DELETE FROM tenant_subscriptions WHERE plan_id = :p"), {"p": plan["plan_id"]}
        )
        conn.execute(
            sa.text("DELETE FROM pricing_plans WHERE plan_id = :p"), {"p": plan["plan_id"]}
        )


def test_a_created_plan_comes_back_with_its_limits_and_no_tenants(a_plan) -> None:
    assert a_plan["event_limit"] == LIMITS["event_limit"]
    assert a_plan["storage_limit_bytes"] == LIMITS["storage_limit_bytes"]
    assert a_plan["accepts_assignments"] is True
    assert a_plan["assigned_tenants"] == 0


def test_a_duplicate_plan_code_is_a_conflict_not_a_second_plan(
    platform_api, full_operator, a_plan
) -> None:
    response = platform_api.post(
        "/v1/platform/plans",
        headers=auth(full_operator),
        json={"plan_code": a_plan["plan_code"], "plan_name": "Impostor", "limits": LIMITS},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "plan_code_already_exists"


def test_a_negative_limit_is_a_field_error(platform_api, full_operator) -> None:
    """Zero is a legitimate limit — it withholds a usage type entirely — so the
    floor is zero and not one, and below it is a field error rather than a 500."""
    response = platform_api.post(
        "/v1/platform/plans",
        headers=auth(full_operator),
        json={
            "plan_code": f"NEG{uuid.uuid4().hex[:6].upper()}",
            "plan_name": "Negative",
            "limits": {**LIMITS, "training_limit": -1},
        },
    )
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["error"]["field_errors"]}
    assert any("training_limit" in field for field in fields), fields


def test_editing_a_plan_changes_it_for_everyone_on_it(platform_api, full_operator, a_plan) -> None:
    """Limits are not versioned; this is the assertion that says so out loud."""
    response = platform_api.patch(
        f"/v1/platform/plans/{a_plan['plan_id']}",
        headers=auth(full_operator),
        json={"limits": {**LIMITS, "training_limit": 99}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["training_limit"] == 99

    detail = platform_api.get(
        f"/v1/platform/plans/{a_plan['plan_id']}", headers=auth(full_operator)
    ).json()
    assert detail["plan"]["training_limit"] == 99


def test_closing_a_plan_refuses_new_joiners(platform_api, full_operator, a_plan, estate) -> None:
    closed = platform_api.post(
        f"/v1/platform/plans/{a_plan['plan_id']}:close", headers=auth(full_operator)
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["accepts_assignments"] is False

    response = platform_api.post(
        f"/v1/platform/tenants/{estate['tenants']['beta']['tenant_id']}:assign-plan",
        headers=auth(full_operator),
        json={"plan_id": a_plan["plan_id"], "reason": "Should not be allowed."},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "plan_closed"


def test_closing_a_plan_does_not_evict_the_tenants_already_on_it(
    platform_api, full_operator, a_plan, estate
) -> None:
    """And re-assigning one of them to it still works, which is the case a
    console that re-saves an unchanged form depends on."""
    tenant_id = estate["tenants"]["beta"]["tenant_id"]
    joined = platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:assign-plan",
        headers=auth(full_operator),
        json={"plan_id": a_plan["plan_id"], "reason": "Joining before it closes."},
    )
    assert joined.status_code == 200, joined.text

    platform_api.post(f"/v1/platform/plans/{a_plan['plan_id']}:close", headers=auth(full_operator))

    detail = platform_api.get(
        f"/v1/platform/plans/{a_plan['plan_id']}", headers=auth(full_operator)
    ).json()
    assert [row["tenant_id"] for row in detail["tenants"]] == [str(tenant_id)]

    again = platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:assign-plan",
        headers=auth(full_operator),
        json={"plan_id": a_plan["plan_id"], "reason": "Re-saving the same plan."},
    )
    assert again.status_code == 200, again.text

    platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:assign-plan",
        headers=auth(full_operator),
        json={"plan_id": str(estate["plans"]["GROWTH"]), "reason": "Restored."},
    )


def test_an_unknown_plan_is_a_404(platform_api, full_operator) -> None:
    response = platform_api.get(f"/v1/platform/plans/{uuid.uuid4()}", headers=auth(full_operator))
    assert response.status_code == 404
