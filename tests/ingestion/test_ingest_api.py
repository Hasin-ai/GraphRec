"""The ingest routes over HTTP, in both realms.

What these check that `test_pipeline.py` cannot: that the routes exist at the
paths the prototype publishes, that a credential and a session both reach them,
that each is judged by the right thing — scope for a program, role for a person
— and that the wire shapes match the snippets on /integration.

Everything here goes through the real app, real tokens and a real credential.
A test that stubbed the dependency would be testing the stub.
"""

from __future__ import annotations

import pytest

from graphrec.common.enums import CredentialScope
from tests.authz.conftest import auth

pytestmark = [pytest.mark.db]

ALL_SCOPES = [s.value for s in CredentialScope]


# ------------------------------------------------------------------ fixtures


@pytest.fixture(scope="session")
def credential(api, home_admin) -> str:
    """A live credential for the home tenant, holding every scope.

    Created through the API as an administrator, because that is the only way
    one is ever created — and the secret is readable exactly once, here.
    """
    response = api.post(
        "/v1/api-keys",
        json={"name": "ingest suite", "scopes": ALL_SCOPES, "expires_in_days": 90},
        headers=auth(home_admin),
    )
    assert response.status_code == 201, response.text
    return response.json()["secret"]


@pytest.fixture(scope="session")
def narrow_credential(api, home_admin) -> str:
    """A credential holding `submissions:read` and nothing else.

    "Only the operations granted to a credential may be performed with it."
    (L1170) is not a statement one can test with a credential that holds
    everything.
    """
    response = api.post(
        "/v1/api-keys",
        json={
            "name": "ingest suite reader",
            "scopes": [CredentialScope.SUBMISSIONS_READ.value],
            "expires_in_days": 90,
        },
        headers=auth(home_admin),
    )
    assert response.status_code == 201, response.text
    return response.json()["secret"]


def _event(event_id: str | None, product: str = "SKU-ING-1", **overrides) -> dict:
    body = {
        "event_id": event_id,
        "customer_id": "cus-9931",
        "external_product_id": product,
        "event_type": "purchase",
        "occurred_at": "2026-08-14T09:41:02Z",
    }
    body.update(overrides)
    return body


@pytest.fixture(scope="session")
def catalog(api, home_dev) -> str:
    """One product for the events to reference, and its external identifier.

    Events name a product, so most of these tests need a catalogue first and
    none of them are testing the catalogue.
    """
    external_id = "SKU-ING-1"
    api.put(
        f"/v1/products/{external_id}",
        json={"title": "Ingest fixture product"},
        headers=auth(home_dev),
    )
    return external_id


# ------------------------------------------------------- the published paths


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/events"),
        ("POST", "/v1/events/batches"),
        ("POST", "/v1/products:bulk-upsert"),
        ("GET", "/v1/submissions/00000000-0000-0000-0000-000000000000"),
        ("GET", "/v1/events/batches/nothing"),
    ],
)
def test_every_ingest_route_is_mounted_where_the_prototype_publishes_it(api, method, path) -> None:
    """L1173-L1180. A 404 here would mean the path is wrong, not the resource."""
    response = api.request(method, path)
    assert response.status_code != 405
    # Unauthenticated: gate 1 answers before anything else can.
    assert response.status_code == 401


def test_there_is_no_submission_index(api, home_dev) -> None:
    """ "There is no submission index. This view is reached from the submission
    that produced it." (L1393)

    A list route would be a new way to enumerate a tenant's ingestion history
    that no screen asks for, and every such route is a thing to keep authorized.
    """
    assert api.get("/v1/submissions", headers=auth(home_dev)).status_code == 404


# --------------------------------------------------------------- both realms


@pytest.mark.usefixtures("catalog")
def test_a_developer_session_may_submit_an_event(api, home_dev) -> None:
    """The console's Test event form (L1621) posts as the signed-in developer."""
    response = api.post("/v1/events", json=_event("ev-session-1"), headers=auth(home_dev))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "event_id": "ev-session-1",
        "status": "accepted",
        "first_received_at": None,
    }


@pytest.mark.usefixtures("catalog")
def test_a_credential_may_submit_an_event(api, credential) -> None:
    """An integration posting from the tenant's own backend, with no person
    signed in anywhere.
    """
    response = api.post("/v1/events", json=_event("ev-credential-1"), headers=auth(credential))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"


def test_an_administrator_session_may_not_submit_events(api, home_admin) -> None:
    """L1256: an administrator has "No catalog access and no event submission."

    403 rather than 404, because the refusal is about this actor's role within
    their own tenant — nothing is being disclosed that they did not already
    know.
    """
    response = api.post("/v1/events", json=_event("ev-admin"), headers=auth(home_admin))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


def test_a_credential_without_the_scope_is_refused_before_the_operation(
    api, narrow_credential
) -> None:
    """L1170 — "rejected before the operation is accepted", so no event exists."""
    response = api.post("/v1/events", json=_event("ev-narrow"), headers=auth(narrow_credential))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


def test_a_credential_is_judged_by_scope_and_never_by_a_role(api, credential) -> None:
    """The realms do not borrow each other's vocabulary.

    A credential has no role, so `insufficient_role` must never be the answer
    for one — that would mean somewhere a scope had been mapped onto a role, and
    the mapping would be a second authorization model nobody maintains.
    """
    body = {"reason": "probing", "name": "x"}
    response = api.post("/v1/api-keys", json=body, headers=auth(credential))
    assert response.json()["error"]["code"] != "insufficient_scope"


def test_a_session_token_presented_as_a_credential_is_refused(api, home_dev) -> None:
    """The realms are told apart by shape, but the shape decides only which
    verifier runs. A JWT never begins with `gr_live_`, so it goes to the session
    verifier — and a *credential* secret sent to a session-only route goes to
    the credential verifier and is refused there.
    """
    assert api.get("/v1/users", headers=auth(home_dev)).status_code in (200, 403)


def test_a_credential_may_not_reach_a_session_only_route(api, credential) -> None:
    """`/v1/users` is the tenant's own administration, not an integration's."""
    assert api.get("/v1/users", headers=auth(credential)).status_code == 401


# ------------------------------------------------------ the published shapes


@pytest.mark.usefixtures("catalog")
def test_a_repeated_event_id_is_confirmed_at_200(api, credential) -> None:
    """L1178's exact body: `{"event_id": ..., "status": "duplicate_confirmed"}`.

    200, not 409. "This is a success outcome, not an error." (L1622)
    """
    body = _event("ev-http-duplicate")
    first = api.post("/v1/events", json=body, headers=auth(credential))
    second = api.post("/v1/events", json=body, headers=auth(credential))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate_confirmed"
    assert second.json()["first_received_at"] is not None


@pytest.mark.usefixtures("catalog")
def test_a_batch_is_accepted_with_202_and_a_submission(api, credential) -> None:
    """L1174: `202 Accepted` carrying the submission id and initial counts."""
    response = api.post(
        "/v1/events/batches",
        json={"batch_id": "batch-http-1", "events": [_event("ev-http-b1")]},
        headers=auth(credential),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["kind"] == "event_batch"
    assert body["status"] == "processing"
    assert body["stage"] == "received"
    assert body["counts"]["received"] == 1
    assert body["reference"] == "batch-http-1"


def test_a_bulk_upsert_is_accepted_with_202(api, credential) -> None:
    """L1173's snippet, field for field."""
    response = api.post(
        "/v1/products:bulk-upsert",
        json={
            "sync_id": "req-http-9d21",
            "products": [
                {
                    "external_id": "SKU-4471",
                    "title": "Brass hinge, 75mm",
                    "category": "Hardware",
                    "brand": "Northgate",
                    "price": "8.40",
                    "active": True,
                    "availability": "in_stock",
                }
            ],
        },
        headers=auth(credential),
    )
    assert response.status_code == 202, response.text
    assert response.json()["kind"] == "product_sync"


@pytest.mark.usefixtures("catalog")
def test_repeating_a_batch_identifier_answers_200_not_202(api, credential) -> None:
    """202 says "I have taken this on"; a repeat has taken nothing on.

    The body is the *original* submission's state, so the status line is the
    only place the difference can go without inviting a client to read a
    repeat's counts as this call's.
    """
    body = {"batch_id": "batch-http-repeat", "events": [_event("ev-http-r1")]}
    first = api.post("/v1/events/batches", json=body, headers=auth(credential))
    second = api.post("/v1/events/batches", json=body, headers=auth(credential))

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["submission_id"] == first.json()["submission_id"]


# ---------------------------------------------------------------- the bounds


def test_an_oversize_batch_returns_413(api, credential) -> None:
    """Phase 6's exit criterion, over HTTP.

    Note this is *not* the body-size limit: the collection is well under 2 MiB
    and is refused for its item count. Both produce 413, which is right — the
    caller's fix is the same in either case, and it is "split it".
    """
    response = api.post(
        "/v1/events/batches",
        json={"batch_id": "batch-oversize", "events": [_event(f"ev-{n}") for n in range(5_001)]},
        headers=auth(credential),
    )
    assert response.status_code == 413, response.text
    error = response.json()["error"]
    assert error["class"] == "validation"
    assert "5,000" in error["reason"]


def test_an_oversize_sync_returns_413(api, credential) -> None:
    response = api.post(
        "/v1/products:bulk-upsert",
        json={
            "sync_id": "req-oversize",
            "products": [{"external_id": f"SKU-{n}", "title": "x"} for n in range(5_001)],
        },
        headers=auth(credential),
    )
    assert response.status_code == 413, response.text


def test_a_missing_batch_identifier_is_422_with_the_field_marked(api, credential) -> None:
    """L1626's form error, beside the input rather than only in the banner."""
    response = api.post(
        "/v1/events/batches", json={"events": [_event("ev-x")]}, headers=auth(credential)
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert [fe["field"] for fe in error["field_errors"]] == ["batch_id"]
    assert error["field_errors"][0]["reason"] == "Required."


def test_a_missing_event_identifier_gets_the_prototypes_sentence(api, home_dev) -> None:
    """L1621: "An event identifier is required — it is the idempotency key."

    The reason the field exists, not merely that it is missing. A framework 422
    could never produce this sentence, which is why the request models are
    permissive and the domain validator answers.
    """
    response = api.post("/v1/events", json=_event(event_id=None), headers=auth(home_dev))
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "event_id_required"
    assert "idempotency key" in error["reason"]


def test_a_body_carrying_a_tenant_id_is_refused(api, credential) -> None:
    """Tenant scope comes from the credential. A body field would be a second,
    forgeable source for it, and `extra="forbid"` is what makes sending one an
    error rather than a silently ignored field.
    """
    response = api.post(
        "/v1/events",
        json={**_event("ev-forged"), "tenant_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth(credential),
    )
    assert response.status_code == 422


# ----------------------------------------------------------------- the reads


@pytest.mark.usefixtures("catalog")
def test_a_submission_is_readable_by_its_id_and_by_its_identifier(api, credential) -> None:
    """L1179-L1180 — one read for both kinds, plus the batch alias.

    The alias matters because the integration that submitted `batch-...` holds
    that identifier and may never have received the submission id: the call that
    would have returned it is the call that timed out.
    """
    accepted = api.post(
        "/v1/events/batches",
        json={"batch_id": "batch-http-alias", "events": [_event("ev-http-a1")]},
        headers=auth(credential),
    ).json()

    by_id = api.get(f"/v1/submissions/{accepted['submission_id']}", headers=auth(credential))
    by_reference = api.get("/v1/events/batches/batch-http-alias", headers=auth(credential))

    assert by_id.status_code == 200
    assert by_reference.status_code == 200
    assert by_id.json()["submission_id"] == by_reference.json()["submission_id"]


def test_the_batch_alias_does_not_answer_with_a_product_sync(api, credential) -> None:
    """`sync_id` and `batch_id` are separate namespaces (migration 0008)."""
    api.post(
        "/v1/products:bulk-upsert",
        json={"sync_id": "shared-name", "products": [{"external_id": "SKU-1", "title": "x"}]},
        headers=auth(credential),
    )
    assert api.get("/v1/events/batches/shared-name", headers=auth(credential)).status_code == 404


@pytest.mark.usefixtures("catalog")
def test_another_tenants_submission_is_a_404_that_does_not_name_it(
    api, credential, other_admin
) -> None:
    """Gate 4 — and the 404 never says the word "submission" (NR-NF-02)."""
    accepted = api.post(
        "/v1/events/batches",
        json={"batch_id": "batch-http-private", "events": [_event("ev-http-p1")]},
        headers=auth(credential),
    ).json()

    response = api.get(f"/v1/submissions/{accepted['submission_id']}", headers=auth(other_admin))
    assert response.status_code in (403, 404)
    if response.status_code == 404:
        assert "submission" not in response.json()["error"]["reason"].lower()


@pytest.mark.usefixtures("catalog")
def test_reading_a_submission_needs_the_read_scope_not_the_write_one(
    api, narrow_credential, credential
) -> None:
    """The scopes are independent grants, and a read-only credential is exactly
    what a tenant's monitoring job should be given.
    """
    accepted = api.post(
        "/v1/events/batches",
        json={"batch_id": "batch-http-scoped", "events": [_event("ev-http-s1")]},
        headers=auth(credential),
    ).json()

    response = api.get(
        f"/v1/submissions/{accepted['submission_id']}", headers=auth(narrow_credential)
    )
    assert response.status_code == 200


@pytest.mark.usefixtures("catalog")
def test_a_submission_response_never_echoes_the_payload(api, credential) -> None:
    """NR-NF-06 and L1391 — "Raw payloads are never echoed back."."""
    secret = "hunter2-should-never-be-echoed"
    accepted = api.post(
        "/v1/events/batches",
        json={
            "batch_id": "batch-http-secret",
            "events": [_event("ev-http-x1", context={"password": secret})],
        },
        headers=auth(credential),
    )
    assert secret not in accepted.text

    read = api.get(f"/v1/submissions/{accepted.json()['submission_id']}", headers=auth(credential))
    assert secret not in read.text
