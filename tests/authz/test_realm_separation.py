"""The two realms, and the wall between them.

A tenant token and a platform token are both valid credentials. Neither may be
spent in the other realm — not because a handler checks, but because the token
carries a realm claim and the verifier for each realm refuses the other outright.

These tests go through HTTP, so they cover the wiring as well as the verifier: a
route mounted under the wrong dependency would pass the unit tests in
`tests/auth/test_tokens.py` and fail here.
"""

from __future__ import annotations

import pytest

from tests.authz.conftest import PASSWORD, auth

pytestmark = pytest.mark.authz

#: Every tenant-realm route. A new one added without a realm test should show up
#: as a gap here rather than in production.
TENANT_ROUTES = [
    ("GET", "/v1/me"),
    ("GET", "/v1/tenant"),
    ("GET", "/v1/users"),
]

PLATFORM_ROUTES = [("GET", "/v1/platform/me")]


@pytest.mark.parametrize(("method", "path"), TENANT_ROUTES)
def test_a_platform_token_cannot_reach_a_tenant_route(api, operator_token, method, path) -> None:
    response = api.request(method, path, headers=auth(operator_token))
    assert response.status_code == 401, f"{path} accepted a platform credential"
    assert response.json()["error"]["class"] == "auth"


@pytest.mark.parametrize(("method", "path"), PLATFORM_ROUTES)
def test_a_tenant_token_cannot_reach_a_platform_route(api, home_admin, method, path) -> None:
    response = api.request(method, path, headers=auth(home_admin))
    assert response.status_code == 401, f"{path} accepted a tenant credential"


def test_an_administrator_token_cannot_reach_a_platform_route(api, home_admin) -> None:
    """Being the *most* privileged tenant role grants nothing in the other realm.

    The realms are not a hierarchy. A tenant administrator is not a junior
    operator, and no amount of tenant-side role gets anywhere near `/v1/platform`.
    """
    assert api.get("/v1/platform/me", headers=auth(home_admin)).status_code == 401


def test_the_operator_response_carries_no_tenant(api, operator_token) -> None:
    body = api.get("/v1/platform/me", headers=auth(operator_token)).json()
    assert "tenant_id" not in body
    assert "tenant_code" not in body


def test_an_operator_sees_only_the_permissions_actually_granted(api, operator_token) -> None:
    body = api.get("/v1/platform/me", headers=auth(operator_token)).json()
    assert body["permissions"] == ["monitoring", "platform"]
    # Not granted, and therefore not present even though the enum defines them.
    for absent in ("plan_management", "platform_scope", "audit"):
        assert absent not in body["permissions"]


def test_a_tenant_cannot_authenticate_on_the_platform_sign_in_route(api, realm) -> None:
    """A tenant member's credentials are not an operator's, even if they are real."""
    response = api.post(
        "/v1/platform/auth/sign-in",
        json={"email": realm["home"]["admin_email"], "password": PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_platform_credentials"


def test_an_operator_cannot_authenticate_on_the_tenant_sign_in_route(api, realm) -> None:
    response = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["home"]["code"],
            "email": realm["operator_email"],
            "password": PASSWORD,
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_a_refresh_token_is_not_a_bearer_credential(api, realm) -> None:
    """It lives for a week. Spending it directly must not work."""
    signed = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["home"]["code"],
            "email": realm["home"]["admin_email"],
            "password": PASSWORD,
        },
    ).json()
    assert api.get("/v1/me", headers=auth(signed["refresh_token"])).status_code == 401


def test_refreshing_rotates_and_the_old_token_stops_working(api, realm) -> None:
    signed = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["home"]["code"],
            "email": realm["home"]["admin_email"],
            "password": PASSWORD,
        },
    ).json()

    rotated = api.post("/v1/auth/refresh", json={"refresh_token": signed["refresh_token"]})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != signed["refresh_token"]

    replay = api.post("/v1/auth/refresh", json={"refresh_token": signed["refresh_token"]})
    assert replay.status_code == 401, "a replayed refresh token was accepted"


def test_signing_out_revokes_the_refresh_token(api, realm) -> None:
    signed = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["home"]["code"],
            "email": realm["home"]["admin_email"],
            "password": PASSWORD,
        },
    ).json()

    assert (
        api.post("/v1/auth/sign-out", json={"refresh_token": signed["refresh_token"]}).status_code
        == 204
    )
    assert (
        api.post("/v1/auth/refresh", json={"refresh_token": signed["refresh_token"]}).status_code
        == 401
    )


def test_signing_out_twice_is_still_204(api, realm) -> None:
    """Reporting "no such session" would let anyone test whether a token is live."""
    signed = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["home"]["code"],
            "email": realm["home"]["admin_email"],
            "password": PASSWORD,
        },
    ).json()
    api.post("/v1/auth/sign-out", json={"refresh_token": signed["refresh_token"]})
    again = api.post("/v1/auth/sign-out", json={"refresh_token": signed["refresh_token"]})
    assert again.status_code == 204


def test_a_wrong_tenant_code_and_a_wrong_password_are_indistinguishable(api, realm) -> None:
    """Otherwise sign-in becomes an oracle for which tenant codes exist."""
    bad_code = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": "ZZZNOSUCH",
            "email": realm["home"]["admin_email"],
            "password": PASSWORD,
        },
    )
    bad_password = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["home"]["code"],
            "email": realm["home"]["admin_email"],
            "password": "definitely-not-the-password",
        },
    )
    assert bad_code.status_code == bad_password.status_code == 401
    assert bad_code.json()["error"]["reason"] == bad_password.json()["error"]["reason"]


def test_a_users_own_email_at_another_tenant_does_not_authenticate(api, realm) -> None:
    """Email is unique per tenant, so the code decides which account is meant."""
    response = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": realm["other"]["code"],
            "email": realm["home"]["admin_email"],
            "password": PASSWORD,
        },
    )
    assert response.status_code == 401
