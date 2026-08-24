"""Failure drills for the serving path (§24 Resilience, §9.4).

A drill is not a unit test. The unit tests around it already prove that the
binder refuses a bundle it cannot read and that `RecommendationService` falls
back when it has no index. What neither of them proves is the *claim*, which is
made about the whole process and phrased in §9.4 as: with the object store gone,
recommendations continue on the popularity lane.

That claim is only true if three independently-written pieces agree — the binder
raises rather than exits, `create_app` starts anyway, and the route reads
`binder.index` as `None` rather than assuming it is loaded. Each of those has its
own test; none of them fails if the *composition* is wrong, and the composition
is what an outage exercises.

Run through `TestClient`, so the lifespan runs and the failure happens where it
would happen in a container: at startup, before the first request.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from graphrec.common.enums import ModelVersionStatus

pytestmark = [pytest.mark.db]


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


@pytest.fixture
def store_is_unreachable(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, issue_credential
):
    """A tenant with an active version whose bundle cannot be read.

    Nothing is published, which is the shape the process sees whether the object
    store is down, the bucket is unreachable, or the artifact was purged by a
    lifecycle rule that was too eager. The replica cannot tell those apart and
    does not need to: all three are "the bundle is not there".
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=4, status=ModelVersionStatus.ACTIVE)
    seed_deployment(tenant_id, active_version_id=version_id, desired_version_id=version_id)
    secret = issue_credential(tenant_id, scopes=["recommendations:read"])
    return tenant_id, version_id, secret


def test_the_fallback_lane_carries_traffic_with_the_model_store_unreachable(
    pinned_app, store_is_unreachable
) -> None:
    """§24: "Fallback lane demonstrated with the model store unreachable".

    The response is a 200 with items in it. `fallback_applied` is true and
    `model_version` is `null` — a null, not an omission, so a caller can tell
    "no model answered this" from "this field was not implemented".
    """
    tenant_id, _version_id, secret = store_is_unreachable

    with TestClient(pinned_app(tenant_id)) as client:
        response = client.post(
            "/v1/recommendations",
            json={"request_id": "drill-store-down", "customer_id": "CUST-1"},
            headers=_auth(secret),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fallback_applied"] is True
    assert body["model_version"] is None
    assert "model_version" in body, "a null is a statement; an absent key is an omission"
    assert body["items"], "a fallback that returns nothing has not fallen back"
    assert body["strategy"] == "fallback"


def test_the_replica_says_it_is_unready_while_it_serves_the_fallback(
    pinned_app, store_is_unreachable
) -> None:
    """Serving and ready are different questions, and the drill needs both answered.

    If this replica reported itself ready the reconciler would count it as
    converged and retire the version that was working (ER-F-06). If it refused
    to serve, §9.4's "recommendations continue degraded" would be false. Both at
    once is the posture, and only this test asserts the pair.

    **The status is `200` and the readiness is in the body**, which is the
    inference app's convention and the opposite of the control API's — see the
    docstring on `readyz` and the healthcheck in
    `deploy/single/docker-compose.serving.yml`, which reads `.ready` rather than
    the code precisely so that "not loaded yet" and "this endpoint is broken"
    stay distinguishable. Asserted here because a drill that accepted either
    would pass against a probe that had quietly started returning 503, and the
    Compose healthcheck would then mark every replica unhealthy at once.
    """
    tenant_id, _version_id, secret = store_is_unreachable

    with TestClient(pinned_app(tenant_id)) as client:
        ready = client.get("/readyz")
        served = client.post(
            "/v1/recommendations",
            json={"request_id": "drill-store-down-2", "customer_id": "CUST-1"},
            headers=_auth(secret),
        )

    assert ready.status_code == 200
    body = ready.json()
    assert body["ready"] is False
    assert body["detail"], "unready without a reason is not diagnosable from the replica"
    assert served.status_code == 200


def test_a_caller_who_declines_the_fallback_is_refused_rather_than_served_stale(
    pinned_app, store_is_unreachable
) -> None:
    """`allow_fallback: false` is a caller saying they would rather have an error.

    Worth drilling separately: the natural implementation of "the store is down,
    fall back" ignores the flag, and the caller who set it is the one who cannot
    use a popularity list — a merchandising surface that would show the same ten
    products to everybody for the duration of the outage.
    """
    tenant_id, _version_id, secret = store_is_unreachable

    with TestClient(pinned_app(tenant_id)) as client:
        response = client.post(
            "/v1/recommendations",
            json={
                "request_id": "drill-store-down-3",
                "customer_id": "CUST-1",
                "allow_fallback": False,
            },
            headers=_auth(secret),
        )

    assert response.status_code == 503, response.text


def test_an_unknown_tenants_credential_is_still_refused_during_the_outage(
    pinned_app, store_is_unreachable, serving_tenants, issue_credential
) -> None:
    """Degradation is not a relaxation.

    The drill that matters after "does it still serve?" is "does it still serve
    only the right people?". A process that opened up while unready would be a
    tenancy failure reachable by taking the object store away.
    """
    tenant_id, _version_id, _secret = store_is_unreachable
    other = issue_credential(serving_tenants["beta"], scopes=["recommendations:read"])

    with TestClient(pinned_app(tenant_id)) as client:
        response = client.post(
            "/v1/recommendations",
            json={"request_id": str(uuid.uuid4()), "customer_id": "CUST-1"},
            headers=_auth(other),
        )

    assert response.status_code == 401, response.text
