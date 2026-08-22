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
    """UC-30's rule applied to ourselves: a gap is a gap, never a pass.

    `unavailable` and `fail` are distinct on purpose. A dependency with no client
    yet has not failed — nothing was asked of it — and reporting it as `pass`
    would be the lie this endpoint exists to prevent. Every one of them carries a
    `detail` saying which phase brings the probe.
    """
    body = client.get("/readyz").json()
    unprobed = [c for c in body["checks"] if c["name"] in {"redis", "object_storage"}]
    assert len(unprobed) == 2
    for check in unprobed:
        assert check["status"] == "unavailable"
        assert check["detail"]

    # Overall is never `pass` while anything is unprobed, so /readyz stays 503.
    assert body["status"] != "pass"


def test_readyz_actually_probes_postgres(client) -> None:
    """From Phase 2 this is a real query, not a placeholder.

    Either outcome is acceptable here — a developer without a database gets
    `fail` — but `unavailable` is not: that would mean the probe silently went
    back to not running.
    """
    postgres = next(
        check for check in client.get("/readyz").json()["checks"] if check["name"] == "postgres"
    )
    assert postgres["status"] in {"pass", "fail"}


def test_a_failed_probe_does_not_leak_connection_details(client, monkeypatch) -> None:
    """A connection error names the host, the port and sometimes the role.

    `/readyz` is typically unauthenticated, so none of that may reach the body
    (NR-NF-06). The exception goes to the log; the response says "unreachable".
    """
    import apps.control_api.routers.health as health

    class _Exploding:
        def __call__(self):
            raise OSError("could not connect to graphrec_app@db.internal:5432")

    monkeypatch.setattr(client.app.state, "sessionmaker", _Exploding())
    body = client.get("/readyz").json()
    postgres = next(c for c in body["checks"] if c["name"] == "postgres")
    assert postgres["status"] == "fail"
    assert postgres["detail"] == "unreachable"
    assert "db.internal" not in client.get("/readyz").text
    assert "graphrec_app" not in client.get("/readyz").text
    assert health.PROBE_TIMEOUT_SECONDS > 0


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
