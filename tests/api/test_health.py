"""Liveness, readiness and the request-correlation contract."""

from __future__ import annotations

from apps.control_api.middleware import REQUEST_ID_HEADER


def test_healthz_is_ok(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_healthz_does_not_depend_on_anything(client) -> None:
    """Liveness must not fail because a dependency is slow.

    Readiness reports Postgres as unprobed in Phase 1; liveness stays 200
    regardless, or an orchestrator would kill a process that is working.
    """
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503


def test_readyz_reports_each_dependency_separately(client) -> None:
    body = client.get("/readyz").json()
    assert {check["name"] for check in body["checks"]} == {
        "postgres",
        "redis",
        "object_storage",
    }


def test_readyz_reports_an_unprobed_check_as_unavailable_not_pass(client) -> None:
    """UC-30's rule applied to ourselves: a gap is a gap, never a pass."""
    body = client.get("/readyz").json()
    assert body["status"] == "unavailable"
    for check in body["checks"]:
        assert check["status"] == "unavailable"
        assert check["detail"]


def test_every_response_carries_a_request_id(client) -> None:
    assert client.get("/healthz").headers[REQUEST_ID_HEADER]


def test_a_supplied_request_id_is_echoed(client) -> None:
    """A caller correlating across services keeps its own identifier."""
    response = client.get("/healthz", headers={REQUEST_ID_HEADER: "caller-abc-123"})
    assert response.headers[REQUEST_ID_HEADER] == "caller-abc-123"


def test_request_ids_are_unique_per_request(client) -> None:
    first = client.get("/healthz").headers[REQUEST_ID_HEADER]
    second = client.get("/healthz").headers[REQUEST_ID_HEADER]
    assert first != second


def test_trailing_slashes_are_rejected_not_redirected(client) -> None:
    """A 307 to a different path drops the Authorization header on some clients."""
    response = client.get("/healthz/")
    assert response.status_code == 404
