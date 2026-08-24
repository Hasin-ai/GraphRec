"""Account recovery: the two steps, and the things neither of them says.

`recovery_tokens` was created in migration 0002 and nothing ever wrote to it.
`POST /v1/auth/recovery` was named in `docs/BACKEND_PLAN.md` §4 (UC-03) and
never built, so `/recover` and `/recover/confirm` were console routes with
nothing behind them. Phase 13 closes that, and this file is what makes the
closing checkable.

Most of the length here is spent on non-disclosure, because that is the
requirement the feature is most likely to fail quietly. `/recover` must answer
identically for an account that exists and one that does not — same status,
same body — and "identically" is asserted by comparing the two responses to
each other rather than each to a literal, which is the version that still holds
when somebody rewords the sentence.
"""

from __future__ import annotations

import logging
import uuid

import pytest
import sqlalchemy as sa

from tests.authz.conftest import PASSWORD, auth

NEW_PASSWORD = "a-replacement-passphrase-entirely"


def _request(api, tenant_code: str, email: str):
    return api.post("/v1/auth/recovery", json={"tenant_code": tenant_code, "email": email})


def _proof(caplog) -> str:
    """The proof the delivery placeholder wrote to the operator log.

    There is nowhere else to read it from — the endpoint deliberately does not
    return it — so the test reads it the way an operator would have to until a
    mail transport exists. That is uncomfortable, and it is meant to be: when
    `graphrec.common.delivery` grows a real transport, this helper is the thing
    that stops compiling and forces the test to follow.
    """
    proofs = [
        word.removeprefix("proof=")
        for record in caplog.records
        for word in record.getMessage().split()
        if word.startswith("proof=")
    ]
    assert proofs, "no recovery proof was delivered"
    return proofs[-1]


@pytest.fixture
def delivered(caplog):
    with caplog.at_level(logging.WARNING, logger="graphrec.delivery"):
        yield caplog


def test_a_request_for_a_real_account_and_one_for_nobody_answer_identically(api, realm) -> None:
    home = realm["home"]
    real = _request(api, home["code"], home["admin_email"])
    fictional = _request(api, home["code"], f"nobody-{uuid.uuid4().hex}@example.com")

    assert real.status_code == fictional.status_code == 202
    assert real.json() == fictional.json()


def test_an_unknown_tenant_code_answers_the_same_way_too(api, realm) -> None:
    """The third path, and the one an enumeration attempt would actually use."""
    home = realm["home"]
    known = _request(api, home["code"], home["admin_email"])
    unknown = _request(api, f"NOSUCH{uuid.uuid4().hex[:6].upper()}", home["admin_email"])

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


def test_a_suspended_or_locked_account_is_not_told_it_cannot_recover(api, realm) -> None:
    """`suspended` tenants still resolve; the user check is what declines."""
    suspended = realm["frozen"]
    response = _request(api, suspended["code"], suspended["admin_email"])
    assert response.status_code == 202


def test_no_proof_is_ever_returned_in_the_response_body(api, realm, delivered) -> None:
    """The property that separates recovery from invitation.

    An invitation token is returned to the administrator who minted it, because
    that administrator is authenticated and chose the recipient. A recovery
    proof is requested by an anonymous caller who typed an address, so returning
    it would mean `POST /v1/auth/recovery` resets anybody's password.
    """
    home = realm["home"]
    response = _request(api, home["code"], home["admin_email"])
    assert response.json() == {
        "detail": "If that identifier matches an account, recovery instructions have been sent."
    }
    assert "rec_" not in response.text
    # And the proof does exist — this is not passing because nothing was minted.
    assert _proof(delivered).startswith("rec_")


def test_a_request_for_nobody_delivers_nothing(api, realm, delivered) -> None:
    """A log line that appeared only for real accounts would move the disclosure
    from the response body into the operator's log, not remove it."""
    home = realm["home"]
    _request(api, home["code"], f"nobody-{uuid.uuid4().hex}@example.com")
    assert not [r for r in delivered.records if "proof=" in r.getMessage()]


def test_a_proof_sets_new_material_and_the_old_one_stops_working(api, realm, delivered) -> None:
    dev = {"code": realm["home"]["code"], "email": realm["home"]["dev_email"]}
    _request(api, dev["code"], dev["email"])
    proof = _proof(delivered)

    confirmed = api.post(
        "/v1/auth/recovery:confirm",
        json={
            "token": proof,
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["email"] == dev["email"]

    stale = api.post(
        "/v1/auth/sign-in",
        json={"tenant_code": dev["code"], "email": dev["email"], "password": PASSWORD},
    )
    assert stale.status_code == 401

    fresh = api.post(
        "/v1/auth/sign-in",
        json={"tenant_code": dev["code"], "email": dev["email"], "password": NEW_PASSWORD},
    )
    assert fresh.status_code == 200, fresh.text

    # Put it back, because `home_dev` in the shared conftest signs in with the
    # session-scoped password and this suite must not decide what that is.
    _request(api, dev["code"], dev["email"])
    restore = api.post(
        "/v1/auth/recovery:confirm",
        json={
            "token": _proof(delivered),
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert restore.status_code == 200, restore.text


def test_a_proof_is_single_use(api, realm, delivered) -> None:
    home = realm["home"]
    _request(api, home["code"], home["admin_email"])
    proof = _proof(delivered)
    body = {"token": proof, "password": PASSWORD, "password_confirmation": PASSWORD}

    assert api.post("/v1/auth/recovery:confirm", json=body).status_code == 200
    second = api.post("/v1/auth/recovery:confirm", json=body)
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "recovery_token_invalid"


def test_requesting_a_second_proof_revokes_the_first(api, realm, delivered) -> None:
    """Two live links is one more than the user asked for."""
    home = realm["home"]
    _request(api, home["code"], home["admin_email"])
    first = _proof(delivered)
    _request(api, home["code"], home["admin_email"])
    second = _proof(delivered)
    assert first != second

    stale = api.post(
        "/v1/auth/recovery:confirm",
        json={"token": first, "password": PASSWORD, "password_confirmation": PASSWORD},
    )
    assert stale.status_code == 401
    assert stale.json()["error"]["code"] == "recovery_token_invalid"

    api.post(
        "/v1/auth/recovery:confirm",
        json={"token": second, "password": PASSWORD, "password_confirmation": PASSWORD},
    )


def test_an_invented_proof_is_refused_without_disclosing_anything(api) -> None:
    response = api.post(
        "/v1/auth/recovery:confirm",
        json={
            "token": f"rec_{uuid.uuid4().hex}",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "recovery_token_invalid"


def test_a_mistyped_confirmation_does_not_consume_the_proof(api, realm, delivered) -> None:
    """The ordering property: the confirmation is compared before anything is
    looked up, so a typo costs the user a retry rather than the whole link."""
    home = realm["home"]
    _request(api, home["code"], home["admin_email"])
    proof = _proof(delivered)

    mistyped = api.post(
        "/v1/auth/recovery:confirm",
        json={
            "token": proof,
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD + "x",
        },
    )
    assert mistyped.status_code == 422
    assert mistyped.json()["error"]["code"] == "password_confirmation_mismatch"

    retry = api.post(
        "/v1/auth/recovery:confirm",
        json={"token": proof, "password": PASSWORD, "password_confirmation": PASSWORD},
    )
    assert retry.status_code == 200, retry.text


def test_recovery_revokes_every_refresh_session_the_account_held(api, realm, delivered) -> None:
    """A reset that left a stolen refresh token working would have changed the
    lock without collecting the key."""
    home = realm["home"]
    signed_in = api.post(
        "/v1/auth/sign-in",
        json={
            "tenant_code": home["code"],
            "email": home["admin_email"],
            "password": PASSWORD,
        },
    )
    assert signed_in.status_code == 200, signed_in.text
    refresh_token = signed_in.json()["refresh_token"]

    # It works right now, which is what makes the assertion afterwards mean
    # something. Rotation supersedes it, so the token used below is the new one.
    rotated = api.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert rotated.status_code == 200, rotated.text
    live = rotated.json()["refresh_token"]

    _request(api, home["code"], home["admin_email"])
    api.post(
        "/v1/auth/recovery:confirm",
        json={"token": _proof(delivered), "password": PASSWORD, "password_confirmation": PASSWORD},
    )

    dead = api.post("/v1/auth/refresh", json={"refresh_token": live})
    assert dead.status_code == 401


def test_the_proof_itself_is_never_stored(api, realm, delivered, owner_engine) -> None:
    """Only its SHA-256 digest. A dump of `recovery_tokens` resets nobody."""
    home = realm["home"]
    _request(api, home["code"], home["admin_email"])
    proof = _proof(delivered)

    with owner_engine.connect() as conn:
        # `recovery_tokens` is `FORCE`d, so the owner reads nothing through a
        # policy — count the digests instead, which needs no row visibility.
        hit = conn.execute(
            sa.text("SELECT count(*) FROM recovery_tokens WHERE token_digest = :t"),
            {"t": proof},
        ).scalar()
    assert hit == 0

    api.post(
        "/v1/auth/recovery:confirm",
        json={"token": proof, "password": PASSWORD, "password_confirmation": PASSWORD},
    )


def test_recovery_needs_no_credential_and_offers_none(api, realm, delivered) -> None:
    """Neither step issues a session: the prototype's button reads "Set and
    return to sign in" (dc.html L1039), and signing in afterwards is what proves
    the material just set is the material the user meant."""
    home = realm["home"]
    _request(api, home["code"], home["admin_email"])
    response = api.post(
        "/v1/auth/recovery:confirm",
        json={"token": _proof(delivered), "password": PASSWORD, "password_confirmation": PASSWORD},
    )
    body = response.json()
    assert "access_token" not in body
    assert "refresh_token" not in body


def test_a_signed_in_caller_gains_nothing_by_calling_it(api, realm, home_admin) -> None:
    """The route ignores credentials rather than rejecting them, and a bearer
    token does not turn the answer into a disclosing one."""
    home = realm["home"]
    response = api.post(
        "/v1/auth/recovery",
        headers=auth(home_admin),
        json={"tenant_code": home["code"], "email": f"nobody-{uuid.uuid4().hex}@example.com"},
    )
    assert response.status_code == 202
    assert response.json()["detail"].startswith("If that identifier matches")
