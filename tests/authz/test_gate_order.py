"""The five gates, and the order they run in.

Each test names the gate it pins and the failure it would represent. The ones
that matter most are the negative-space tests: a foreign resource answering 403
instead of 404, or a suspended tenant's token still working, would each be a real
leak that a happy-path suite would never notice.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from tests.authz.conftest import PASSWORD, auth
from tests.isolation.conftest import _force_lifted

pytestmark = pytest.mark.authz


# --------------------------------------------------------- gate 1: identity


def test_no_credential_is_401(api) -> None:
    response = api.get("/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["class"] == "auth"


def test_a_garbage_credential_is_401(api) -> None:
    response = api.get("/v1/me", headers=auth("not-a-token"))
    assert response.status_code == 401


def test_a_missing_header_and_a_bad_token_say_the_same_thing(api) -> None:
    """Otherwise the API confirms whether what you sent was shaped like a token."""
    missing = api.get("/v1/me").json()["error"]
    bad = api.get("/v1/me", headers=auth("eyJhbGciOiJFZERTQSJ9.e30.x")).json()["error"]
    assert missing["reason"] == bad["reason"]
    assert missing["code"] == bad["code"]


def test_a_valid_credential_reaches_the_route(api, home_admin, realm) -> None:
    response = api.get("/v1/me", headers=auth(home_admin))
    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(realm["home"]["tenant_id"])


# ----------------------------------------------------- gate 2: tenant state


def test_a_suspended_tenant_cannot_sign_in(api, realm) -> None:
    """Gate 2 refuses before anything else is considered."""
    response = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["frozen"]["code"],
            "email": realm["frozen"]["admin_email"],
            "password": PASSWORD,
        },
    )
    # Sign-in itself succeeds at gate 1 — the credentials are real — and the
    # refusal comes at the first authenticated request. What must not happen is a
    # 200 from a tenant screen.
    if response.status_code == 200:
        token = response.json()["access_token"]
        follow_up = api.get("/v1/tenant", headers=auth(token))
        assert follow_up.status_code == 403
        assert follow_up.json()["error"]["code"] == "tenant_not_active"


def test_the_suspension_message_says_it_is_not_tenant_actionable(api, realm) -> None:
    """dc.html L1059 — the console renders this as a dead end, correctly."""
    signed = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["frozen"]["code"],
            "email": realm["frozen"]["admin_email"],
            "password": PASSWORD,
        },
    )
    if signed.status_code != 200:
        pytest.skip("sign-in refuses a suspended tenant outright; gate 2 is covered above")
    body = api.get("/v1/tenant", headers=auth(signed.json()["access_token"])).json()["error"]
    assert "Platform Administrator" in body["reason"]


def test_a_freshly_registered_tenant_is_pending_and_cannot_work(api, owner_engine) -> None:
    """Registration yields `pending`, and `pending` is not operable.

    Pinned because it is surprising and because nothing else covers it: every
    other test in this suite seeds an `active` tenant directly, so the
    registration path was exercised end to end for the first time against the
    containerised stack, not here.

    The sequence is deliberate and each step matters. Sign-in **succeeds** —
    gate 1 is about the credential, and the credential is real. The refusal
    comes at gate 2, on the first authenticated request, with the prototype's
    wording for a transition only a Platform Administrator can make.

    What this also documents is a gap: **no route in Phase 2 can move a tenant
    from `pending` to `active`.** That is platform tenant management, which is
    Phase 4. Until then a self-registered tenant is stranded, and this test will
    start failing the moment that changes — which is the point.

    The gap is a consequence of the schema rather than an omission in the
    routers. `ck_tenants_active_requires_plan` (migration 0002, from SRS §5.2.2:
    "A Tenant must reference one active Pricing Plan when activated") makes
    `active` unreachable without a plan, and registration deliberately passes
    `plan_id=None` — choosing a plan is not the registrant's decision to make.
    """
    suffix = uuid.uuid4().hex[:8].upper()
    registered = api.post(
        "/v1/tenants",
        json={
            "tenant_name": f"Northgate {suffix}",
            "tenant_code": f"NGS{suffix}",
            "email": f"admin-{suffix.lower()}@example.com",
            "password": PASSWORD,
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["status"] == "pending"

    signed_in = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": f"NGS{suffix}",
            "email": f"admin-{suffix.lower()}@example.com",
            "password": PASSWORD,
        },
    )
    assert signed_in.status_code == 200, "gate 1 is about the credential, and it is valid"

    refused = api.get("/v1/me", headers=auth(signed_in.json()["access_token"]))
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "tenant_not_active"
    assert "Platform Administrator" in refused.json()["error"]["reason"]

    # This is the only test that registers a tenant the `realm` fixture does not
    # own, so it cleans up after itself. No role holds DELETE on `tenants`, so
    # teardown is the owner with `FORCE` briefly lifted — the same escape hatch
    # the fixtures use, in a `finally`-shaped place and nowhere else.
    with owner_engine.begin() as conn, _force_lifted(conn, "tenants"):
        conn.execute(
            sa.text("DELETE FROM tenants WHERE tenant_id = :t"),
            {"t": registered.json()["tenant_id"]},
        )


# ------------------------------------------------------------ gate 3: role


def test_a_developer_may_read_the_user_list(api, home_dev) -> None:
    """Read is open to both roles — seeing your own colleagues is not a leak."""
    assert api.get("/v1/users", headers=auth(home_dev)).status_code == 200


def test_a_developer_may_not_create_a_user(api, home_dev) -> None:
    response = api.post(
        "/v1/users",
        headers=auth(home_dev),
        json={"email": "nope@example.com", "display_name": "Nope", "role": "tenant_developer"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


def test_the_role_refusal_tells_the_console_not_to_retry(api, home_dev) -> None:
    body = api.post(
        "/v1/users",
        headers=auth(home_dev),
        json={"email": "nope2@example.com", "display_name": "Nope", "role": "tenant_developer"},
    ).json()["error"]
    assert "There is nothing to retry here." in body["reason"]
    assert body["retryable"] is False


def test_an_administrator_may_create_a_user(api, home_admin) -> None:
    response = api.post(
        "/v1/users",
        headers=auth(home_admin),
        json={
            "email": f"new-{uuid.uuid4().hex[:8]}@example.com",
            "display_name": "New Person",
            "role": "tenant_developer",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["status"] == "invited"
    # The token comes back once, because Phase 2 has no mail transport. It must
    # stop appearing here the moment invitations are delivered out of band.
    assert body["invitation_token"].startswith("inv_")


# ------------------------------------------------------- gate 4: ownership


def test_a_foreign_user_is_404_and_never_403(api, home_admin, realm) -> None:
    """The single most important assertion in this file.

    A 403 here would confirm that the identifier names a real user somewhere —
    which is precisely the cross-tenant leak the whole design exists to prevent.
    """
    response = api.patch(
        f"/v1/users/{realm['other']['dev_id']}/role",
        headers=auth(home_admin),
        json={"role": "tenant_administrator"},
    )
    assert response.status_code == 404
    assert response.status_code != 403


def test_a_foreign_user_and_an_absent_one_are_indistinguishable(api, home_admin, realm) -> None:
    foreign = api.patch(
        f"/v1/users/{realm['other']['dev_id']}/role",
        headers=auth(home_admin),
        json={"role": "tenant_administrator"},
    )
    absent = api.patch(
        f"/v1/users/{uuid.uuid4()}/role",
        headers=auth(home_admin),
        json={"role": "tenant_administrator"},
    )
    assert foreign.status_code == absent.status_code == 404
    assert foreign.json()["error"]["reason"] == absent.json()["error"]["reason"]
    assert foreign.json()["error"]["code"] == absent.json()["error"]["code"]


def test_the_404_never_names_the_resource_type(api, home_admin) -> None:
    body = api.patch(
        f"/v1/users/{uuid.uuid4()}/role",
        headers=auth(home_admin),
        json={"role": "tenant_developer"},
    ).json()["error"]
    assert "user" not in body["reason"].lower()


def test_the_user_list_never_contains_another_tenants_member(api, home_admin, realm) -> None:
    listed = api.get("/v1/users", headers=auth(home_admin)).json()["users"]
    ids = {user["tenant_user_id"] for user in listed}
    assert str(realm["other"]["admin_id"]) not in ids
    assert str(realm["other"]["dev_id"]) not in ids
    assert str(realm["home"]["admin_id"]) in ids


def test_gate_3_runs_before_gate_4(api, home_dev, realm) -> None:
    """A developer naming a foreign identifier is refused for the role, not the row.

    Both answers are safe here, but the order is worth pinning: gate 3 does not
    require touching the resource, so refusing there costs no lookup and cannot
    leak through timing.
    """
    response = api.patch(
        f"/v1/users/{realm['other']['dev_id']}/role",
        headers=auth(home_dev),
        json={"role": "tenant_developer"},
    )
    assert response.status_code == 403


# ---------------------------------------------------- gate 5: resource state


def test_the_last_active_administrator_cannot_be_demoted(api, home_admin, realm) -> None:
    """dc.html L1244, and a 409 — the actor is entitled; the state forbids it."""
    response = api.patch(
        f"/v1/users/{realm['home']['admin_id']}/role",
        headers=auth(home_admin),
        json={"role": "tenant_developer"},
    )
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["class"] == "conflict"
    assert body["reason"] == "The last active administrator cannot be demoted or disabled."


def test_the_last_active_administrator_cannot_be_disabled(api, home_admin, realm) -> None:
    response = api.patch(
        f"/v1/users/{realm['home']['admin_id']}/status",
        headers=auth(home_admin),
        json={"status": "disabled"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_active_administrator"


def test_a_409_is_only_reachable_by_someone_entitled_to_it(api, home_dev, realm) -> None:
    """The state conflict must sit behind the role gate, not in front of it.

    If it did not, a developer could discover that a tenant has exactly one
    administrator — a fact about the tenant's staffing that their role does not
    entitle them to.
    """
    response = api.patch(
        f"/v1/users/{realm['home']['admin_id']}/role",
        headers=auth(home_dev),
        json={"role": "tenant_developer"},
    )
    assert response.status_code == 403
