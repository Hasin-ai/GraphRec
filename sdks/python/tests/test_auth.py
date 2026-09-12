from __future__ import annotations

import asyncio
from typing import List

import pytest

import graphrec_sdk as g
from graphrec_sdk import errors

from .conftest import MockAPI, error, make_async_client, make_client, tokens

USAGE = {
    "period_start": "2026-09-01T00:00:00Z",
    "period_end": "2026-10-01T00:00:00Z",
    "reset_at": "2026-10-01T00:00:00Z",
    "dimensions": [
        {
            "type": "accepted_events",
            "used": 1200,
            "limit": 50000,
            "remaining": 48800,
            "unit": "count",
        },
        {
            "type": "training_cpu_seconds",
            "used": 12.5,
            "limit": None,
            "remaining": None,
            "unit": "seconds",
        },
    ],
    "last_reconciled_at": "2026-09-11T10:00:00Z",
    "project_defaults": True,
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_password_auth_logs_in_once_and_reuses_token(api: MockAPI, sleeps: List[float]) -> None:
    api.queue("POST", "/v1/auth/login", tokens("tok-1"), tokens("tok-2"))
    api.on("GET", "/v1/usage", USAGE)
    clock = FakeClock()
    auth = g.PasswordAuth("admin@shop.test", "correct horse", clock=clock)
    with make_client(api, sleeps, api_key=None, auth=auth) as client:
        client.usage.get()
        client.usage.get()
        assert api.paths() == ["POST /v1/auth/login", "GET /v1/usage", "GET /v1/usage"]
        assert api.last().headers["Authorization"] == "Bearer tok-1"
        assert api.calls[0].json() == {"email": "admin@shop.test", "password": "correct horse"}

        clock.now += 900 - 30  # inside the expiry skew window
        client.usage.get()
        assert api.paths()[-2:] == ["POST /v1/auth/login", "GET /v1/usage"]
        assert api.last().headers["Authorization"] == "Bearer tok-2"
        assert auth.tokens is not None and auth.tokens.access_token == "tok-2"


def test_token_expired_triggers_single_relogin(api: MockAPI, sleeps: List[float]) -> None:
    api.queue("POST", "/v1/auth/login", tokens("tok-1"), tokens("tok-2"))
    api.queue("GET", "/v1/usage", error(401, "token_expired"), USAGE)
    with make_client(
        api, sleeps, api_key=None, email="admin@shop.test", password="pw-123456"
    ) as client:
        summary = client.usage.get()
    assert summary.get(g.UsageType.ACCEPTED_EVENTS).remaining == 48800  # type: ignore[union-attr]
    assert api.paths() == [
        "POST /v1/auth/login",
        "GET /v1/usage",
        "POST /v1/auth/login",
        "GET /v1/usage",
    ]
    assert sleeps == []


def test_persistent_token_expired_is_raised(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/auth/login", tokens())
    api.on("GET", "/v1/usage", lambda _r: error(401, "token_expired"))
    with make_client(
        api, sleeps, api_key=None, email="a@shop.test", password="pw-123456"
    ) as client:
        with pytest.raises(errors.TokenExpiredError):
            client.usage.get()
    assert len([p for p in api.paths() if p == "GET /v1/usage"]) == 2


def test_static_bearer_token_is_not_refreshed(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", "/v1/usage", lambda _r: error(401, "token_expired"))
    with make_client(api, sleeps, api_key=None, access_token="static") as client:
        with pytest.raises(errors.TokenExpiredError):
            client.usage.get()
    assert len(api.calls) == 1


def test_failed_login_surfaces_authentication_error(api: MockAPI, sleeps: List[float]) -> None:
    api.on("POST", "/v1/auth/login", lambda _r: error(401, "authentication_failed"))
    with make_client(api, sleeps, api_key=None, email="a@shop.test", password="wrong-pw") as client:
        with pytest.raises(errors.AuthenticationError):
            client.usage.get()


def test_async_password_auth(api: MockAPI) -> None:
    api.queue("POST", "/v1/auth/login", tokens("tok-a"))
    api.on("GET", "/v1/usage", USAGE)

    async def main() -> None:
        async with make_async_client(
            api, api_key=None, email="a@shop.test", password="pw-123456"
        ) as client:
            first, second = await asyncio.gather(client.usage.get(), client.usage.get())
            assert first.get("accepted_events") is not None
            assert second.project_defaults is True

    asyncio.run(main())
    assert api.paths().count("POST /v1/auth/login") == 1
    assert api.last().headers["Authorization"] == "Bearer tok-a"


def test_usage_dimension_helpers() -> None:
    summary = g.models.UsageSummary.model_validate(USAGE)
    events = summary.get("accepted_events")
    assert events is not None and events.utilization == pytest.approx(0.024)
    cpu = summary.get(g.UsageType.TRAINING_CPU_SECONDS)
    assert cpu is not None and cpu.utilization is None and not cpu.is_exhausted
