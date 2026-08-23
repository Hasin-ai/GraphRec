"""Suspending, restoring and re-planning a tenant — and the row each leaves.

Every action here is one of ER-F-11's eight audited actions, so each test
asserts two things that a handler could easily get half right: the state moved,
*and* the history says who moved it. An implementation that commits the status
change and writes the audit row in a separate transaction passes the first
assertion on a machine where nothing goes wrong, which is the only kind of
machine it will ever be tested on.

The reason field is required and is not decoration. The status, the actor and
the timestamp are all mechanical; the reason is the only part of the row a
person wrote, and it is what a dispute six months later is actually about.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from tests.platform.conftest import EVERYTHING, auth


def _status_of(engine, tenant_id) -> str:
    with engine.connect() as conn, conn.begin():
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        value: str = conn.execute(
            sa.text("SELECT status FROM tenants WHERE tenant_id = :t"), {"t": tenant_id}
        ).scalar_one()
    return value


def _audit_rows(api, token, tenant_id) -> list[dict]:
    response = api.get(
        "/v1/platform/audit-logs",
        headers=auth(token),
        params={"tenant": str(tenant_id), "limit": 200},
    )
    assert response.status_code == 200, response.text
    return response.json()["entries"]


def test_suspending_a_tenant_moves_it_and_records_who_moved_it(
    platform_api, full_operator, estate, estate_engine
) -> None:
    tenant_id = estate["tenants"]["beta"]["tenant_id"]
    response = platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:status",
        headers=auth(full_operator),
        json={"status": "suspended", "reason": "Non-payment, third notice."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "suspended"
    assert _status_of(estate_engine, tenant_id) == "suspended"

    rows = _audit_rows(platform_api, full_operator, tenant_id)
    suspensions = [row for row in rows if row["action"] == "tenant"]
    assert suspensions, "the tenant moved and the history does not say so"
    assert suspensions[0]["actor_type"] == "platform_administrator"
    assert suspensions[0]["outcome"] == "succeeded"

    # Put it back, so the ordering of tests in this file is not load-bearing.
    platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:status",
        headers=auth(full_operator),
        json={"status": "active", "reason": "Payment received."},
    )


def test_moving_a_tenant_to_the_state_it_is_already_in_is_a_conflict(
    platform_api, full_operator, estate
) -> None:
    """Not a silent success. A no-op that reports success writes an audit row
    saying an operator suspended an account they did not suspend."""
    tenant_id = estate["tenants"]["cold"]["tenant_id"]
    response = platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:status",
        headers=auth(full_operator),
        json={"status": "suspended", "reason": "Belt and braces."},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tenant_status_unchanged"


def test_a_blank_reason_is_refused(platform_api, full_operator, estate) -> None:
    tenant_id = estate["tenants"]["acme"]["tenant_id"]
    response = platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:status",
        headers=auth(full_operator),
        json={"status": "suspended", "reason": "   "},
    )
    assert response.status_code in (400, 422)


def test_a_refused_status_change_is_still_recorded(platform_api, full_operator, estate) -> None:
    """The refusal survives the rollback that took the change with it.

    This is the whole point of writing refusals on a second connection: the
    transaction that would have carried the audit row is exactly the one that
    unwound. An attempt to suspend an account is a thing an investigation wants
    to see whether or not it succeeded.
    """
    tenant_id = estate["tenants"]["cold"]["tenant_id"]
    platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:status",
        headers=auth(full_operator),
        json={"status": "suspended", "reason": "Recorded even though refused."},
    )
    rows = _audit_rows(platform_api, full_operator, tenant_id)
    assert any(row["outcome"] == "cancelled" for row in rows), (
        "a refused action left no trace; the refusal was written into the "
        "transaction that rolled back"
    )


def test_assigning_a_plan_moves_the_tenant_onto_it(platform_api, full_operator, estate) -> None:
    tenant_id = estate["tenants"]["acme"]["tenant_id"]
    response = platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:assign-plan",
        headers=auth(full_operator),
        json={"plan_id": str(estate["plans"]["STARTER"]), "reason": "Downgrade requested."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["plan_code"] == "STARTER"

    detail = platform_api.get(
        f"/v1/platform/tenants/{tenant_id}", headers=auth(full_operator)
    ).json()
    assert detail["sections"]["plan"]["data"]["plan_code"] == "STARTER"

    platform_api.post(
        f"/v1/platform/tenants/{tenant_id}:assign-plan",
        headers=auth(full_operator),
        json={"plan_id": str(estate["plans"]["GROWTH"]), "reason": "Restored."},
    )


def test_granting_an_override_returns_it_and_audits_it_as_a_quota_action(
    platform_api, full_operator, estate
) -> None:
    tenant_id = estate["tenants"]["beta"]["tenant_id"]
    response = platform_api.post(
        f"/v1/platform/tenants/{tenant_id}/quota-overrides",
        headers=auth(full_operator),
        json={
            "usage_type": "events",
            "limit_value": 5_000_000,
            "reason": "Seasonal peak; agreed with the account manager.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["limit_value"] == 5_000_000
    assert body["usage_type"] == "events"

    rows = _audit_rows(platform_api, full_operator, tenant_id)
    assert any(row["action"] == "quota" for row in rows)


def test_an_operator_without_plan_management_cannot_assign_a_plan(
    platform_api, operator, estate
) -> None:
    """Reading a tenant and re-pricing it are different permissions (L1439)."""
    token = operator("platform")
    response = platform_api.post(
        f"/v1/platform/tenants/{estate['tenants']['acme']['tenant_id']}:assign-plan",
        headers=auth(token),
        json={"plan_id": str(estate["plans"]["STARTER"])},
    )
    assert response.status_code == 403


def test_the_estate_list_is_searchable_and_filterable(platform_api, full_operator, estate) -> None:
    response = platform_api.get(
        "/v1/platform/tenants",
        headers=auth(full_operator),
        params={"search": estate["tenants"]["cold"]["code"]},
    )
    assert response.status_code == 200, response.text
    codes = [row["tenant_code"] for row in response.json()["tenants"]]
    assert codes == [estate["tenants"]["cold"]["code"]]

    filtered = platform_api.get(
        "/v1/platform/tenants", headers=auth(full_operator), params={"status": "suspended"}
    ).json()
    assert all(row["status"] == "suspended" for row in filtered["tenants"])


def test_acting_on_a_tenant_that_does_not_exist_is_a_404(platform_api, full_operator) -> None:
    response = platform_api.post(
        f"/v1/platform/tenants/{uuid.uuid4()}:status",
        headers=auth(full_operator),
        json={"status": "suspended", "reason": "Nobody home."},
    )
    assert response.status_code == 404


def test_every_permission_is_needed_by_something(platform_api, operator, estate) -> None:
    """A permission no route consults is a permission that means nothing.

    Asserted by taking each one away in turn and finding a route that notices.
    """
    tenant_id = estate["tenants"]["acme"]["tenant_id"]
    probes = {
        "platform": ("GET", f"/v1/platform/tenants/{tenant_id}"),
        "plan_management": ("GET", "/v1/platform/plans"),
        "platform_scope": ("GET", "/v1/platform/usage"),
        "monitoring": ("GET", "/v1/platform/status"),
        "audit": ("GET", "/v1/platform/failures"),
    }
    for permission, (method, path) in probes.items():
        without = operator(*[name for name in EVERYTHING if name != permission])
        response = platform_api.request(method, path, headers=auth(without))
        assert response.status_code == 403, f"{path} did not require {permission}"

        with_it = operator(*EVERYTHING)
        assert platform_api.request(method, path, headers=auth(with_it)).status_code == 200
