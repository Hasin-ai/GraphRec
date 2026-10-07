"""A-05 / NR-F-02: refresh tokens rotate once and a replayed token revokes the user's sessions."""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration
JSON = {"Accept": "application/json"}


def _signed_in(client):
    tag = uuid4().hex
    created = client.post("/v1/tenants", json={"name": f"Refresh {tag}", "admin_email": f"{tag}@example.org"},
                          headers={**JSON, "Idempotency-Key": tag})
    tokens = client.post("/v1/auth/setup-password", headers=JSON,
                         json={"setup_token": created.json()["setup_token"], "password": f"Refresh-{tag}!"})
    assert tokens.status_code == 200, tokens.text
    return tokens.json()


def _bearer(tokens):
    return {**JSON, "Authorization": f"Bearer {tokens['access_token']}"}


def test_nr_f_02_refresh_rotates_and_new_access_token_works(client):
    first = _signed_in(client)
    rotated = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}, headers=JSON)
    assert rotated.status_code == 200, rotated.text
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"] != first["access_token"]
    assert second["email"] == first["email"] and second["user_role"] == first["user_role"]
    assert client.get("/v1/subscription", headers=_bearer(second)).status_code == 200
    # The successor can itself be rotated.
    third = client.post("/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}, headers=JSON)
    assert third.status_code == 200


def test_nr_f_02_reused_refresh_token_revokes_every_session(client):
    first = _signed_in(client)
    second = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}, headers=JSON).json()
    replay = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}, headers=JSON)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_refresh_token"
    # The legitimate successor and its access token stop working too.
    assert client.post("/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}, headers=JSON).status_code == 401
    assert client.get("/v1/subscription", headers=_bearer(second)).status_code == 401


def test_nr_f_02_unknown_and_logged_out_tokens_are_rejected(client):
    assert client.post("/v1/auth/refresh", json={"refresh_token": "x" * 64}, headers=JSON).status_code == 401
    tokens = _signed_in(client)
    assert client.post("/v1/auth/logout", headers=_bearer(tokens)).status_code == 204
    after = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}, headers=JSON)
    assert after.status_code == 401


def test_nr_f_02_refresh_does_not_cross_tenants(client):
    a, b = _signed_in(client), _signed_in(client)
    rotated = client.post("/v1/auth/refresh", json={"refresh_token": a["refresh_token"]}, headers=JSON).json()
    created = client.put("/v1/products/only-a", json={"external_id": "only-a", "title": "A"}, headers=_bearer(rotated))
    assert created.status_code == 200, created.text
    assert client.get("/v1/products/only-a", headers=_bearer(b)).status_code == 404
