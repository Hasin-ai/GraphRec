"""Accepting an invitation — the one authenticated-user path that starts with
no credential at all.

The interesting property is not that it works. It is that a route which runs
unbound, resolves a tenant from a caller-supplied string and then writes a row
into that tenant cannot be steered into the wrong tenant, cannot be replayed,
and cannot be used to grant a role the administrator did not choose.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from tests.authz.conftest import PASSWORD, auth

pytestmark = [pytest.mark.authz, pytest.mark.db]

NEW_PASSWORD = "another-perfectly-adequate-passphrase"


def _invite(api, token: str, *, role: str = "tenant_developer") -> dict:
    email = f"invitee-{uuid.uuid4().hex[:10]}@example.com"
    response = api.post(
        "/v1/users",
        headers=auth(token),
        json={"email": email, "display_name": "Invitee", "role": role},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    body["email"] = email
    return body


# ------------------------------------------------------------------ issuing


def test_only_an_administrator_may_invite(api, home_dev) -> None:
    """Gate 3. A developer inviting a user would be a privilege-escalation path."""
    response = api.post(
        "/v1/users",
        headers=auth(home_dev),
        json={"email": "nope@example.com", "display_name": "No", "role": "tenant_developer"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


def test_an_invited_user_cannot_sign_in(api, home_admin, realm) -> None:
    """The account exists and is listed, and the credential does not work yet."""
    invited = _invite(api, home_admin)
    assert invited["user"]["status"] == "invited"

    response = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["home"]["code"],
            "email": invited["email"],
            "password": PASSWORD,
        },
    )
    assert response.status_code == 401


def test_the_token_is_returned_once_and_never_stored_in_the_clear(
    api, home_admin, seed_engine, realm
) -> None:
    invited = _invite(api, home_admin)
    token = invited["invitation_token"]
    assert token.startswith("inv_")

    with seed_engine.connect() as conn, conn.begin():
        conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(realm["home"]["tenant_id"])},
        )
        stored = conn.execute(
            sa.text("SELECT token_digest FROM invitations WHERE invitation_id = :i"),
            {"i": invited["invitation_id"]},
        ).scalar_one()
    assert token not in stored
    assert stored != token


def test_listing_users_never_exposes_an_invitation_token(api, home_admin) -> None:
    _invite(api, home_admin)
    response = api.get("/v1/users", headers=auth(home_admin))
    assert response.status_code == 200
    assert "inv_" not in response.text
    assert "invitation_token" not in response.text


# ---------------------------------------------------------------- accepting


def test_accepting_activates_the_account_and_permits_sign_in(api, home_admin, realm) -> None:
    invited = _invite(api, home_admin)
    response = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"

    signed_in = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["home"]["code"],
            "email": invited["email"],
            "password": NEW_PASSWORD,
        },
    )
    assert signed_in.status_code == 200, signed_in.text


def test_the_accepted_account_lands_in_the_inviting_tenant(api, home_admin, other_admin) -> None:
    """The route runs unbound, so this is the assertion that matters most."""
    invited = _invite(api, home_admin)
    accepted = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert accepted.status_code == 200

    # Visible to the tenant that issued it...
    home_list = api.get("/v1/users", headers=auth(home_admin)).json()["users"]
    assert invited["email"] in {u["email"] for u in home_list}

    # ...and to nobody else.
    other_list = api.get("/v1/users", headers=auth(other_admin)).json()["users"]
    assert invited["email"] not in {u["email"] for u in other_list}


def test_the_role_comes_from_the_invitation_not_the_request(api, home_admin) -> None:
    """`extra="forbid"` means an invitee cannot even ask for a different role."""
    invited = _invite(api, home_admin, role="tenant_developer")
    response = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
            "role": "tenant_administrator",
        },
    )
    assert response.status_code == 422

    clean = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert clean.status_code == 200
    assert clean.json()["role"] == "tenant_developer"


def test_an_invitation_cannot_be_accepted_twice(api, home_admin) -> None:
    invited = _invite(api, home_admin)
    body = {
        "token": invited["invitation_token"],
        "password": NEW_PASSWORD,
        "password_confirmation": NEW_PASSWORD,
    }
    assert api.post("/v1/invitations:accept", json=body).status_code == 200

    replayed = api.post("/v1/invitations:accept", json=body)
    assert replayed.status_code == 401
    assert replayed.json()["error"]["code"] == "invitation_invalid"


def test_an_unknown_token_is_refused_with_the_same_answer(api, home_admin) -> None:
    """Indistinguishable from a spent one — no oracle for which links are live."""
    invited = _invite(api, home_admin)
    spent = {
        "token": invited["invitation_token"],
        "password": NEW_PASSWORD,
        "password_confirmation": NEW_PASSWORD,
    }
    api.post("/v1/invitations:accept", json=spent)

    unknown = api.post(
        "/v1/invitations:accept",
        json={
            "token": "inv_" + uuid.uuid4().hex,
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert unknown.status_code == 401
    assert unknown.json() == api.post("/v1/invitations:accept", json=spent).json() | {
        "error": unknown.json()["error"] | {"reference": unknown.json()["error"]["reference"]}
    }
    assert unknown.json()["error"]["code"] == "invitation_invalid"


def test_an_expired_invitation_is_refused(api, home_admin, seed_engine, realm) -> None:
    invited = _invite(api, home_admin)
    with seed_engine.connect() as conn, conn.begin():
        conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(realm["home"]["tenant_id"])},
        )
        conn.execute(
            sa.text(
                "UPDATE invitations SET expires_at = now() - interval '1 hour' "
                "WHERE invitation_id = :i"
            ),
            {"i": invited["invitation_id"]},
        )

    response = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invitation_invalid"


def test_a_revoked_invitation_is_refused(api, home_admin, seed_engine, realm) -> None:
    invited = _invite(api, home_admin)
    with seed_engine.connect() as conn, conn.begin():
        conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(realm["home"]["tenant_id"])},
        )
        conn.execute(
            sa.text("UPDATE invitations SET revoked_at = now() WHERE invitation_id = :i"),
            {"i": invited["invitation_id"]},
        )

    response = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert response.status_code == 401


def test_a_mismatched_confirmation_does_not_consume_the_invitation(api, home_admin) -> None:
    """A typo must not burn the link — the invitee has no way to get another."""
    invited = _invite(api, home_admin)
    mismatched = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD + "x",
        },
    )
    assert mismatched.status_code == 422
    assert mismatched.json()["error"]["code"] == "password_confirmation_mismatch"

    retried = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert retried.status_code == 200


def test_accepting_requires_no_credential_and_grants_none(api, home_admin) -> None:
    """The response is the user, not a session. dc.html L1045 returns to sign-in."""
    invited = _invite(api, home_admin)
    response = api.post(
        "/v1/invitations:accept",
        json={
            "token": invited["invitation_token"],
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" not in body
    assert "refresh_token" not in body
    # Nor the tenant it belongs to: the invitee learns nothing they did not send.
    assert "tenant_id" not in body


def test_an_email_already_in_the_tenant_is_a_conflict(api, home_admin, realm) -> None:
    response = api.post(
        "/v1/users",
        headers=auth(home_admin),
        json={
            "email": realm["home"]["dev_email"],
            "display_name": "Duplicate",
            "role": "tenant_developer",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_already_exists"


def test_the_same_email_may_be_invited_by_a_different_tenant(api, home_admin, other_admin) -> None:
    """Email is unique *per tenant* (dc.html L1235), not globally."""
    invited = _invite(api, home_admin)
    response = api.post(
        "/v1/users",
        headers=auth(other_admin),
        json={"email": invited["email"], "display_name": "Same person", "role": "tenant_developer"},
    )
    assert response.status_code == 201, response.text
