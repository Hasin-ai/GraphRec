"""The data plane over HTTP, through the process that actually serves it.

`TestClient(create_app(settings))` runs the lifespan, so the binder in these
tests is the one the container would have: it refreshes at startup, it reports
through `/readyz`, and nothing here reaches past a route to arrange it.

Three things are asserted at this boundary and nowhere else, because nowhere
else is where a caller stands:

* the process refuses a credential belonging to any other tenant, in the same
  words it refuses an invalid one;
* `model_version` and `strategy` are on every recommendation response (ER-F-05);
* `/readyz` says *why* it is not ready, which is what turns a failed activation
  into something diagnosable from the replica.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from apps.inference.main import MissingTenantPinError, create_app

pytestmark = [pytest.mark.db]


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _recommend(client: TestClient, secret: str, *, request_id: str) -> None:
    """Make the request the feedback will answer.

    Feedback is not free-standing: it names a `recommendation_requests` row,
    and a click with nothing to attribute it to is a numerator without a
    denominator. So the tests below earn their request rather than inventing
    an id, which is also what an integrator does.
    """
    response = client.post(
        "/v1/recommendations",
        json={"request_id": request_id, "customer_id": "CUST-1"},
        headers=_auth(secret),
    )
    assert response.status_code == 200, response.text


def _reason(response) -> str:  # httpx.Response; not worth the import here
    body = response.json()["error"]
    return str(body["code"])


# ----------------------------------------------------------------- the pin


def test_the_process_refuses_to_start_without_a_tenant_pin(settings) -> None:
    """SRS §6.4. An unpinned inference process is not a degraded deployment —
    it is a process with no answer to "whose catalogue is this?", and it fails
    at import of its app rather than on the first request."""
    with pytest.raises(MissingTenantPinError):
        create_app(settings.model_copy(update={"tenant_id": None}))


async def test_a_credential_from_another_tenant_is_refused_as_invalid(
    ready_tenant, serving_tenants, pinned_app, issue_credential
) -> None:
    """A valid credential presented to the wrong process.

    The refusal must not distinguish itself from an invalid one. "Your key is
    fine, but this process serves someone else" confirms that both tenants
    exist and that the caller holds a working credential for one of them.
    """
    tenant_id, _ = ready_tenant
    stranger = issue_credential(serving_tenants["beta"])
    # A credential of this tenant's own, carrying a scope that is not the one
    # the route wants. Zero scopes is not an option — the schema forbids it,
    # because a credential that can do nothing is a mistake, not a policy.
    own = issue_credential(tenant_id, scopes=["feedback:write"])

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        foreign = client.post(
            "/v1/recommendations",
            json={"request_id": "req-1", "customer_id": "CUST-1"},
            headers=_auth(stranger),
        )
        nonsense = client.post(
            "/v1/recommendations",
            json={"request_id": "req-2", "customer_id": "CUST-1"},
            headers=_auth("gr_live_nothing.at-all"),
        )
        # This one gets past gate 1 and fails at gate 3, so the difference
        # between it and the foreign credential is the tenant, not the syntax.
        scopeless = client.post(
            "/v1/recommendations",
            json={"request_id": "req-3", "customer_id": "CUST-1"},
            headers=_auth(own),
        )

    assert foreign.status_code == 401
    assert nonsense.status_code == 401
    assert _reason(foreign) == _reason(nonsense) == "invalid_credentials"
    assert scopeless.status_code == 403
    assert _reason(scopeless) == "insufficient_scope"


async def test_a_missing_scope_is_refused_before_any_work_is_recorded(
    ready_tenant, pinned_app, issue_credential, bound_serving
) -> None:
    """dc.html L1170. A refused call writes no `recommendation_requests` row.

    Charging a tenant's ledger for a call that was rejected at the gate would
    make an integration mistake cost money, which is the sort of thing that is
    only ever discovered on an invoice.
    """
    tenant_id, _ = ready_tenant
    secret = issue_credential(tenant_id, scopes=["feedback:write"])

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recommendations",
            json={"request_id": "req-scope", "customer_id": "CUST-1"},
            headers=_auth(secret),
        )

    assert response.status_code == 403
    assert _reason(response) == "insufficient_scope"

    import sqlalchemy as sa

    async with bound_serving(tenant_id) as session:
        recorded = await session.scalar(
            sa.text("SELECT count(*) FROM recommendation_requests WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    assert recorded == 0


# --------------------------------------------------------------- readiness


async def test_readyz_reports_unready_with_a_reason_before_a_bundle_binds(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, pinned_app
) -> None:
    """Nothing was ever uploaded, so the process is up and cannot answer.

    `/readyz` returns 200 with `ready: false` rather than a 5xx: the body is the
    signal the driver reads, and an error status would make "unready" and
    "unreachable" the same observation.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id, desired_version_id=version_id)

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    body = ready.json()
    assert body["ready"] is False
    assert body["model_version"] is None
    assert body["detail"]
    assert body["tenant_id"] == str(tenant_id)


async def test_readyz_names_the_resident_version_once_bound(ready_tenant, pinned_app) -> None:
    tenant_id, version_id = ready_tenant

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        body = client.get("/readyz").json()

    assert body["ready"] is True
    assert body["detail"] is None
    assert body["model_version"] == {"version_id": str(version_id), "version_number": 3}


async def test_readyz_stays_unready_when_the_bundle_belongs_to_another_tenant(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    publish_bundle,
    pinned_app,
) -> None:
    """BACKEND_PLAN L1678, at the boundary the driver watches.

    The process starts — it must, or there is nothing to ask — and never becomes
    ready. That is precisely the shape the reconciler times out on, so a bundle
    with the wrong tenant in its manifest ends as a failed activation with the
    previous version still serving, and not as a cross-tenant answer.
    """
    alpha, beta = serving_tenants["alpha"], serving_tenants["beta"]
    seed_catalogue(alpha)
    version_id = seed_model_version(alpha, version_number=1)
    publish_bundle(alpha, version_id, manifest_tenant_id=beta)
    seed_deployment(alpha, desired_version_id=version_id)

    with TestClient(pinned_app(alpha), raise_server_exceptions=False) as client:
        body = client.get("/readyz").json()

    assert body["ready"] is False
    assert body["detail"] is not None
    # And the detail says what is wrong without naming who it belongs to.
    assert str(beta) not in body["detail"]


# --------------------------------------------------------- recommendations


async def test_every_recommendation_response_carries_its_model_version_and_strategy(
    ready_tenant, pinned_app, issue_credential
) -> None:
    """ER-F-05's two required fields, on the successful path."""
    tenant_id, version_id = ready_tenant
    secret = issue_credential(tenant_id)

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recommendations",
            json={"request_id": "req-model", "customer_id": "CUST-1", "top_n": 5},
            headers=_auth(secret),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_version"] == {"version_id": str(version_id), "version_number": 3}
    assert body["strategy"]
    assert body["ordering_policy_version"] >= 1
    assert 1 <= len(body["items"]) <= 5
    assert [item["rank"] for item in body["items"]] == list(range(1, len(body["items"]) + 1))
    assert all(item["candidate_source"] for item in body["items"])


async def test_the_session_route_answers_without_a_customer_and_never_echoes_the_session(
    ready_tenant, pinned_app, issue_credential
) -> None:
    """XR-F-09. The session id goes in; no field in the response can carry it back."""
    tenant_id, _ = ready_tenant
    secret = issue_credential(tenant_id)
    session_id = "sess-7f3a-not-to-be-echoed"

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recommendations/session",
            json={"request_id": "req-anon", "session_id": session_id, "top_n": 4},
            headers=_auth(secret),
        )

    assert response.status_code == 200
    assert session_id not in response.text
    assert response.json()["items"]


async def test_a_body_with_an_unknown_field_is_refused_rather_than_ignored(
    ready_tenant, pinned_app, issue_credential
) -> None:
    """`extra="forbid"`. A caller who sends `tenant_id` believing it does
    something needs to be told it does not."""
    tenant_id, _ = ready_tenant
    secret = issue_credential(tenant_id)

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recommendations",
            json={
                "request_id": "req-extra",
                "customer_id": "CUST-1",
                "tenant_id": str(uuid.uuid4()),
            },
            headers=_auth(secret),
        )

    assert response.status_code == 422


async def test_a_request_naming_neither_a_customer_nor_a_session_is_refused(
    ready_tenant, pinned_app, issue_credential
) -> None:
    tenant_id, _ = ready_tenant
    secret = issue_credential(tenant_id)

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recommendations",
            json={"request_id": "req-nobody"},
            headers=_auth(secret),
        )

    assert response.status_code == 422


async def test_an_unready_process_falls_back_and_says_so(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    pinned_app,
    issue_credential,
) -> None:
    """No model resident, and the tenant still gets an answer.

    This is the whole point of the fallback lanes: a cold start, a failed
    activation and a replica still downloading are all outages of the *model*,
    not of the shop. The answer is popularity, `model_version` is `null` and
    `fallback_applied` is true — ER-F-05's fields are what make the degradation
    legible rather than silent.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id, desired_version_id=version_id)
    secret = issue_credential(tenant_id)

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        assert client.get("/readyz").json()["ready"] is False
        response = client.post(
            "/v1/recommendations",
            json={"request_id": "req-cold", "customer_id": "CUST-1"},
            headers=_auth(secret),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_version"] is None
    assert body["fallback_applied"] is True
    assert body["items"]


async def test_a_caller_who_refuses_a_fallback_is_told_the_model_is_not_ready(
    serving_tenants,
    seed_catalogue,
    seed_model_version,
    seed_deployment,
    pinned_app,
    issue_credential,
) -> None:
    """`allow_fallback: false` — 503 and retryable, not a 200 with no items.

    An empty list is a legitimate answer to "nothing suits this customer".
    Using it for "this process has no model" would make an outage
    indistinguishable from a considered result, and a client would cache it.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id, desired_version_id=version_id)
    secret = issue_credential(tenant_id)

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/recommendations",
            json={
                "request_id": "req-strict",
                "customer_id": "CUST-1",
                "allow_fallback": False,
            },
            headers=_auth(secret),
        )

    assert response.status_code == 503
    assert response.json()["error"]["retryable"] is True


# ---------------------------------------------------------------- feedback


async def test_feedback_counts_duplicates_separately_from_acceptances(
    ready_tenant, pinned_app, issue_credential
) -> None:
    """A retried batch is the normal consequence of a timeout on the caller's
    side. Reporting the duplicates is what lets a client tell "you accepted my
    twenty again" from "you counted them twice"."""
    tenant_id, _ = ready_tenant
    secret = issue_credential(tenant_id)
    batch = {
        "request_id": "req-feedback",
        "impressions": [
            {"event_id": "imp-1", "external_product_id": "SKU-01", "position": 1},
            {"event_id": "imp-2", "external_product_id": "SKU-02", "position": 2},
        ],
    }

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        _recommend(client, secret, request_id="req-feedback")
        first = client.post("/v1/feedback/impressions", json=batch, headers=_auth(secret))
        again = client.post("/v1/feedback/impressions", json=batch, headers=_auth(secret))

    assert first.status_code == 200, first.text
    assert first.json()["accepted"] == 2
    assert first.json()["duplicates"] == 0
    assert again.status_code == 200
    assert again.json()["accepted"] == 0
    assert again.json()["duplicates"] == 2


async def test_feedback_for_a_request_nobody_made_is_not_found(
    ready_tenant, pinned_app, issue_credential
) -> None:
    """Feedback names the recommendation it answers, and an unknown name is a
    404 rather than an orphan row.

    Accepting it would put a click in the ledger with nothing to attribute it
    to, and every rate this platform reports — click-through, conversion — is a
    ratio whose denominator is the request.
    """
    tenant_id, _ = ready_tenant
    secret = issue_credential(tenant_id)

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/feedback/impressions",
            json={
                "request_id": "req-never-happened",
                "impressions": [
                    {"event_id": "imp-x", "external_product_id": "SKU-01", "position": 1}
                ],
            },
            headers=_auth(secret),
        )

    assert response.status_code == 404
    # And it does not say what kind of thing was missing (gate 4's rule).
    assert _reason(response) == "recommendation_request_unknown"


async def test_feedback_names_unknown_products_without_refusing_the_batch(
    ready_tenant, pinned_app, issue_credential
) -> None:
    """One bad id in twenty must not lose the other nineteen.

    The caller's catalogue and ours drift — a product deleted upstream is still
    on a page somebody is looking at. The batch is applied and the ids we could
    not place are named back, which is a report the integrator can act on.
    """
    tenant_id, _ = ready_tenant
    secret = issue_credential(tenant_id)

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        _recommend(client, secret, request_id="req-click")
        response = client.post(
            "/v1/feedback/clicks",
            json={
                "request_id": "req-click",
                "events": [
                    {"event_id": "clk-1", "external_product_id": "SKU-03"},
                    {"event_id": "clk-2", "external_product_id": "SKU-NOT-OURS"},
                ],
            },
            headers=_auth(secret),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["received"] == 2
    assert body["accepted"] == 1
    assert body["unknown_products"] == ["SKU-NOT-OURS"]


async def test_feedback_requires_its_own_scope(ready_tenant, pinned_app, issue_credential) -> None:
    """A read-only integration must not be able to write conversions. Revenue
    attribution is derived from them."""
    tenant_id, _ = ready_tenant
    secret = issue_credential(tenant_id, scopes=["recommendations:read"])

    with TestClient(pinned_app(tenant_id), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/feedback/conversions",
            json={
                "request_id": "req-conv",
                "events": [{"event_id": "cnv-1", "external_product_id": "SKU-01", "value": 42.5}],
            },
            headers=_auth(secret),
        )

    assert response.status_code == 403
    assert _reason(response) == "insufficient_scope"
