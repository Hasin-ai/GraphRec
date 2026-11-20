"""A-01: authentication limits are shared across processes, keyed by the real
client behind a trusted proxy, and keep limiting when Redis is unavailable."""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from graphrec_core.usage.admission import AdmissionController
from tests.test_admission import _redis_up

REDIS_URL = "redis://localhost:6379/0"


@pytest.mark.skipif(not _redis_up(), reason="Redis (REDIS_URL) is not reachable")
def test_two_api_processes_share_one_login_window():
    first, second = AdmissionController(REDIS_URL), AdmissionController(REDIS_URL)
    first.clear_windows("t-login")
    assert first.check_window("t-login", "account:a", 2, 60) is None
    assert second.check_window("t-login", "account:a", 2, 60) is None
    # A third attempt is refused whichever process receives it.
    assert first.check_window("t-login", "account:a", 2, 60) is not None
    assert second.check_window("t-login", "account:a", 2, 60) is not None
    # Other subjects are unaffected.
    assert second.check_window("t-login", "account:b", 2, 60) is None
    first.clear_windows("t-login")


def test_redis_outage_falls_back_to_a_per_process_limit_not_to_unlimited():
    class Down:
        def register_script(self, _):
            def run(**_kwargs):
                raise ConnectionError("redis is down")
            return run

        def ping(self):
            raise ConnectionError("redis is down")

    controller = AdmissionController(None, client=Down())
    controller._redis_errors = lambda: (ConnectionError,)  # type: ignore[method-assign]
    results = [controller.check_window("t-down", "source:1.2.3.4", 3, 60) for _ in range(5)]
    assert results[:3] == [None, None, None]
    assert all(r is not None and r >= 1 for r in results[3:])
    assert controller.status()["status"] == "degraded"


def test_local_window_memory_is_bounded():
    controller = AdmissionController(None)
    controller.local.MAX_WINDOWS = 10
    refused = [controller.check_window("t-bound", f"s{i}", 5, 60) for i in range(20)]
    assert len(controller.local._windows) <= 10
    assert any(r is not None for r in refused[10:])


def test_trusted_proxy_exposes_each_browser_address():
    async def whoami(request):
        return PlainTextResponse(request.client.host)

    app = ProxyHeadersMiddleware(Starlette(routes=[Route("/", whoami)]), trusted_hosts=["*"])
    client = TestClient(app)
    assert client.get("/", headers={"X-Forwarded-For": "203.0.113.7"}).text == "203.0.113.7"
    assert client.get("/", headers={"X-Forwarded-For": "198.51.100.2"}).text == "198.51.100.2"
