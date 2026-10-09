"""Tests for Phase 2: Observability, JSON logging, and Prometheus metrics."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.config import Settings
from app.graphrec import build_local
from app.main import create_app
from app.observability import JsonFormatter, correlation_id_var


class FakeClient:
    async def health(self):
        return {"status": "ok"}

    async def close(self):
        pass


@pytest.fixture
def test_app():
    cfg = Settings(
        graphrec_api_key="gr_live_phase2_test_key",
        reel_secret_key="dev-secret-key-phase2-testing-minimum32",
        reel_env="development",
        reel_rate_limit_per_minute=3,
        reel_metrics_token="test-metrics-token-123",
    )
    svc = build_local(cfg, FakeClient())
    return create_app(settings=cfg, svc=svc)


def test_json_formatter_with_correlation_id():
    formatter = JsonFormatter()
    token = correlation_id_var.set("cid-test-999")
    try:
        record = logging.LogRecord(
            name="reel.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=42,
            msg="hello observability",
            args=(),
            exc_info=None,
        )
        record.duration_ms = 12.34
        record.route = "/api/reel/films"
        formatted = formatter.format(record)
        parsed = json.loads(formatted)
        assert parsed["logger"] == "reel.test"
        assert parsed["level"] == "info"
        assert parsed["message"] == "hello observability"
        assert parsed["correlation_id"] == "cid-test-999"
        assert parsed["duration_ms"] == 12.34
        assert parsed["route"] == "/api/reel/films"
        assert "ts" in parsed
    finally:
        correlation_id_var.reset(token)


@pytest.mark.asyncio
async def test_metrics_token_protection(test_app):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated request to /metrics should return 401
        res = await client.get("/metrics")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"

        # 2. Wrong token should return 401
        res = await client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
        assert res.status_code == 401

        # 3. Valid token returns 200 with text/plain exposition format
        res = await client.get("/metrics", headers={"Authorization": "Bearer test-metrics-token-123"})
        assert res.status_code == 200
        assert "text/plain" in res.headers["content-type"]
        body = res.text
        assert "# HELP reel_http_requests_total" in body
        assert "# HELP reel_rate_limit_hits_total" in body
        assert "reel_metrics_shared" in body


@pytest.mark.asyncio
async def test_metrics_observation_and_rate_limit_hit(test_app):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Perform 3 requests (limit is 3)
        for _ in range(3):
            r = await client.get("/api/reel/films")
            assert r.status_code == 200

        # 4th request must be rate-limited (429)
        r4 = await client.get("/api/reel/films")
        assert r4.status_code == 429
        assert r4.json()["error"]["code"] == "rate_limited"

        # Verify /metrics reflects the request count and rate limit hit
        metrics_resp = await client.get("/metrics", headers={"Authorization": "Bearer test-metrics-token-123"})
        assert metrics_resp.status_code == 200
        body = metrics_resp.text
        assert 'reel_http_requests_total{method="GET",route="/api/reel/films",status="2xx"}' in body
        assert 'reel_http_requests_total{method="GET",route="/api/reel/films",status="4xx"}' in body
        assert "reel_rate_limit_hits_total" in body
        # Should be at least 1 hit
        rate_lines = [l for l in body.splitlines() if l.startswith("reel_rate_limit_hits_total ")]
        assert len(rate_lines) == 1
        count = int(rate_lines[0].split()[1])
        assert count >= 1
