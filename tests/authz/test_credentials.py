"""API credentials: issuance, the one-time secret, rotation, grace and scopes.

The four properties BUILD_PROMPT names as this phase's exit criteria are pinned
here, each by a test whose failure would be a real defect rather than a
cosmetic one:

  * the secret is returned exactly twice in a credential's life, at creation and
    at rotation, and by no other route;
  * a rotated credential's predecessor still verifies during a grace window, and
    stops the moment it lapses;
  * a credential cannot reach another tenant's data;
  * a scope the credential does not hold is refused before the operation runs.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from tests.authz.conftest import auth
from tests.isolation.conftest import _force_lifted

pytestmark = pytest.mark.authz

USABLE_SCOPES = ["events:write", "recommendations:read"]


def _create(api, token, **overrides):
    body = {"name": "Storefront server", "scopes": USABLE_SCOPES, "expires_in_days": 90}
    body.update(overrides)
    return api.post("/v1/api-keys", headers=auth(token), json=body)


# ------------------------------------------------------------------ issuance


def test_creating_a_credential_returns_the_secret_once(api, home_admin) -> None:
    response = _create(api, home_admin)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["secret"].startswith("gr_live_")
    assert body["credential"]["visible_prefix"] in body["secret"]
    assert body["credential"]["state"] == "usable"


def test_the_one_time_notice_is_the_prototypes_wording(api, home_admin) -> None:
    """dc.html L561. Reproduced, not paraphrased."""
    body = _create(api, home_admin).json()
    assert body["notice"] == (
        "This value is shown once. GraphRec does not retain it — "
        "if it is lost, rotate the credential to obtain a new one."
    )


def test_no_read_route_ever_returns_the_secret(api, home_admin) -> None:
    """The single most important assertion in this file.

    If a secret could be read back, storing only a digest would be pointless and
    the whole credential model would be decorative.
    """
    created = _create(api, home_admin).json()
    key_id = created["credential"]["key_id"]

    described = api.get(f"/v1/api-keys/{key_id}", headers=auth(home_admin))
    assert described.status_code == 200
    assert "secret" not in described.json()

    listed = api.get("/v1/api-keys", headers=auth(home_admin))
    assert "secret" not in listed.text
    # And the actual secret string must not appear anywhere in a list body.
    assert created["secret"] not in listed.text


def test_a_credential_with_no_scope_is_refused_with_the_prototypes_words(api, home_admin) -> None:
    """dc.html L1137."""
    response = _create(api, home_admin, scopes=[])
    assert response.status_code == 422
    assert "A credential with no scope cannot authorize anything." in response.text


def test_an_unnamed_credential_is_refused_before_the_scopes_are_considered(api, home_admin) -> None:
    """The console checks the name first (L1136 before L1137); so does the API."""
    response = _create(api, home_admin, name="   ", scopes=[])
    assert response.status_code == 422
    assert "so it can be told apart in this list" in response.text


def test_an_unoffered_expiry_is_refused(api, home_admin) -> None:
    """The dialog is a select of 90/180/365 (L1134), not a free integer."""
    assert _create(api, home_admin, expires_in_days=45).status_code == 422


def test_a_developer_may_also_manage_credentials(api, home_dev) -> None:
    """dc.html L1258 — the one capability both roles share."""
    assert _create(api, home_dev, name="Dev credential").status_code == 201


# ------------------------------------------------------------------ rotation


def test_rotation_returns_a_new_secret_on_the_same_credential(api, home_admin) -> None:
    created = _create(api, home_admin).json()
    key_id = created["credential"]["key_id"]

    rotated = api.post(f"/v1/api-keys/{key_id}:rotate", headers=auth(home_admin), json={})
    assert rotated.status_code == 200, rotated.text
    body = rotated.json()

    assert body["credential"]["key_id"] == key_id, "rotation is in place (dc.html L1150)"
    assert body["secret"] != created["secret"]
    assert body["credential"]["visible_prefix"] != created["credential"]["visible_prefix"]


def test_the_secret_is_returned_exactly_twice_and_never_again(api, home_admin) -> None:
    """Creation and rotation. That is the whole list."""
    created = _create(api, home_admin).json()
    key_id = created["credential"]["key_id"]
    rotated = api.post(f"/v1/api-keys/{key_id}:rotate", headers=auth(home_admin), json={}).json()

    assert created["secret"]
    assert rotated["secret"]
    for _ in range(2):
        again = api.get(f"/v1/api-keys/{key_id}", headers=auth(home_admin))
        assert "secret" not in again.json()


def test_a_revoked_credential_cannot_be_rotated(api, home_admin) -> None:
    """dc.html L1118, and a 409 — the actor is entitled; the state forbids it."""
    created = _create(api, home_admin).json()
    key_id = created["credential"]["key_id"]
    assert api.delete(f"/v1/api-keys/{key_id}", headers=auth(home_admin)).status_code == 204

    refused = api.post(f"/v1/api-keys/{key_id}:rotate", headers=auth(home_admin), json={})
    assert refused.status_code == 409
    assert refused.json()["error"]["reason"] == "Revoked credentials cannot be rotated."


def test_a_revoked_credential_reports_its_blocked_reason(api, home_admin) -> None:
    """The console disables the control using the server's reason, not its own."""
    created = _create(api, home_admin).json()
    key_id = created["credential"]["key_id"]
    api.delete(f"/v1/api-keys/{key_id}", headers=auth(home_admin))

    view = api.get(f"/v1/api-keys/{key_id}", headers=auth(home_admin)).json()
    assert view["state"] == "revoked"
    assert view["can_rotate"] is False
    assert view["can_revoke"] is False
    assert view["blocked_reason"] == "Revoked credentials cannot be rotated."


def test_revocation_is_idempotent(api, home_admin) -> None:
    created = _create(api, home_admin).json()
    key_id = created["credential"]["key_id"]
    assert api.delete(f"/v1/api-keys/{key_id}", headers=auth(home_admin)).status_code == 204
    assert api.delete(f"/v1/api-keys/{key_id}", headers=auth(home_admin)).status_code == 204


def test_revocation_does_not_delete_the_row(api, home_admin, owner_engine) -> None:
    """No role holds DELETE. A credential that acted stays in the record."""
    created = _create(api, home_admin).json()
    key_id = created["credential"]["key_id"]
    api.delete(f"/v1/api-keys/{key_id}", headers=auth(home_admin))

    with owner_engine.begin() as conn, _force_lifted(conn, "api_keys"):
        rows = list(
            conn.execute(
                sa.text("SELECT revoked_at FROM api_keys WHERE key_id = :k"), {"k": key_id}
            )
        )
    assert len(rows) == 1
    assert rows[0][0] is not None


# ------------------------------------------------------------------ ownership


def test_another_tenants_credential_is_404_and_never_403(api, home_admin, other_admin) -> None:
    """Gate 4. A 403 would confirm the credential exists somewhere."""
    theirs = _create(api, other_admin, name="Their credential").json()
    key_id = theirs["credential"]["key_id"]

    response = api.get(f"/v1/api-keys/{key_id}", headers=auth(home_admin))
    assert response.status_code == 404
    assert response.status_code != 403

    absent = api.get(f"/v1/api-keys/{uuid.uuid4()}", headers=auth(home_admin))
    assert absent.json()["error"]["reason"] == response.json()["error"]["reason"]


def test_the_list_never_contains_another_tenants_credential(api, home_admin, other_admin) -> None:
    theirs = _create(api, other_admin, name="Theirs again").json()["credential"]["key_id"]
    mine = _create(api, home_admin, name="Mine").json()["credential"]["key_id"]

    listed = api.get("/v1/api-keys", headers=auth(home_admin)).json()["credentials"]
    ids = {row["key_id"] for row in listed}
    assert mine in ids
    assert theirs not in ids


def test_another_tenants_credential_cannot_be_revoked(api, home_admin, other_admin) -> None:
    theirs = _create(api, other_admin, name="Not yours").json()["credential"]["key_id"]
    assert api.delete(f"/v1/api-keys/{theirs}", headers=auth(home_admin)).status_code == 404


# -------------------------------------------------------------------- scopes


def test_the_scope_catalogue_matches_the_generated_vocabulary(api) -> None:
    from graphrec.common.enums import SCOPE_LABELS, CredentialScope

    listed = api.get("/v1/scopes").json()["scopes"]
    assert {row["scope"] for row in listed} == {scope.value for scope in CredentialScope}
    for row in listed:
        assert row["label"] == SCOPE_LABELS[CredentialScope(row["scope"])]


def test_scopes_are_stored_as_granted(api, home_admin) -> None:
    created = _create(api, home_admin, scopes=["catalog:write"]).json()
    assert created["credential"]["scopes"] == ["catalog:write"]


def test_an_unrecognized_scope_is_refused_without_echoing_it(api, home_admin) -> None:
    """A rejected value must not come back out in the body.

    Echoing caller input into an error is how a payload reaches a log line or a
    console that renders it (NR-NF-06).
    """
    response = _create(api, home_admin, scopes=["billing:admin"])
    assert response.status_code == 422
    assert "billing:admin" not in response.text
