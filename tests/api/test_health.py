"""Liveness, readiness and the request-correlation contract."""

from __future__ import annotations

from graphrec.http import REQUEST_ID_HEADER


def test_healthz_is_ok(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_healthz_does_not_depend_on_anything(client, monkeypatch) -> None:
    """Liveness must not fail because a dependency is slow.

    Asserted by breaking a dependency and checking liveness does not notice.
    Before Phase 16 this test read `/readyz` returning 503 as its evidence,
    which proved nothing about `/healthz` and stopped being true the moment the
    probes started passing.
    """

    class _Exploding:
        def __call__(self):
            raise OSError("the database is gone")

    monkeypatch.setattr(client.app.state, "sessionmaker", _Exploding())
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503


def test_readyz_reports_each_dependency_separately(client) -> None:
    body = client.get("/readyz").json()
    assert {check["name"] for check in body["checks"]} == {
        "postgres",
        "redis",
        "object_storage",
    }


def test_readyz_probes_every_dependency_for_real(client) -> None:
    """No check may be `unavailable` merely because nobody wrote the probe.

    This is the test that Phase 16 existed to make pass. From Phase 2 until
    Phase 16 the Redis and object-storage checks were hard-coded to
    `unavailable` with a detail naming the phase that would fix them — both of
    which had shipped — so `/readyz` answered 503 for the entire life of the
    platform and no orchestrator would ever have routed to it.

    A developer with the stack up gets three passes. One without gets `fail`
    from Postgres or storage, which is honest. What must never appear again is
    a `detail` promising a future phase.
    """
    body = client.get("/readyz").json()
    for check in body["checks"]:
        assert "Phase" not in (check["detail"] or ""), check
    assert body["status"] == "pass", body
    assert client.get("/readyz").status_code == 200


def test_readyz_reports_an_unrun_check_as_unavailable_not_pass(client, monkeypatch) -> None:
    """UC-30's rule applied to ourselves: a gap is a gap, never a pass.

    Redis is the dependency this platform can degrade around — metering falls
    back to an in-memory counter — so its outage is `unavailable`, and the
    endpoint still refuses traffic without calling the process broken.
    """

    class _DeadCache:
        async def ping(self):
            raise OSError("connection refused at cache.internal:6379")

    monkeypatch.setattr(client.app.state, "redis", _DeadCache())
    response = client.get("/readyz")
    body = response.json()
    redis = next(c for c in body["checks"] if c["name"] == "redis")
    assert redis["status"] == "unavailable"
    assert redis["detail"] == "unreachable"
    assert body["status"] == "unavailable"
    assert response.status_code == 503
    assert "cache.internal" not in response.text


def test_an_unreachable_object_store_is_a_failure_not_a_degradation(client, monkeypatch) -> None:
    """There is no degraded mode for storage, so it is `fail`.

    And it is caught at all only because `ArtifactStore.probe` exists: `exists`
    reports a missing key and an unreachable bucket identically, so a probe
    built on it would have called a dead store `pass`.
    """

    class _DeadStore:
        def probe(self):
            raise OSError("could not reach bucket graphrec at minio.internal:9000")

    monkeypatch.setattr(client.app.state, "artifact_store", _DeadStore())
    response = client.get("/readyz")
    body = response.json()
    storage = next(c for c in body["checks"] if c["name"] == "object_storage")
    assert storage["status"] == "fail"
    assert storage["detail"] == "unreachable"
    assert body["status"] == "fail"
    assert response.status_code == 503
    assert "minio.internal" not in response.text


def test_a_hanging_dependency_is_reported_not_waited_on(client, monkeypatch) -> None:
    """A probe that can hang teaches an orchestrator nothing.

    The timeout is dropped to something a test can afford; what is under test is
    that the endpoint answers at all, and names the dependency that did not.
    """
    import asyncio

    import apps.control_api.routers.health as health

    monkeypatch.setattr(health, "PROBE_TIMEOUT_SECONDS", 0.05)

    class _Hanging:
        async def ping(self):
            await asyncio.sleep(30)

    monkeypatch.setattr(client.app.state, "redis", _Hanging())
    body = client.get("/readyz").json()
    redis = next(c for c in body["checks"] if c["name"] == "redis")
    assert redis["status"] == "unavailable"
    assert "did not answer within" in redis["detail"]


def test_the_probes_run_concurrently(client, monkeypatch) -> None:
    """Three serial timeouts is six seconds to say "not ready".

    Measured rather than asserted structurally: two dependencies are made to
    take a tenth of a second each, and the whole request must take closer to one
    tenth than to two.
    """
    import asyncio
    import time

    class _Slow:
        async def ping(self):
            await asyncio.sleep(0.2)

    class _SlowStore:
        def probe(self):
            time.sleep(0.2)

    monkeypatch.setattr(client.app.state, "redis", _Slow())
    monkeypatch.setattr(client.app.state, "artifact_store", _SlowStore())
    started = time.monotonic()
    client.get("/readyz")
    assert time.monotonic() - started < 0.35


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
