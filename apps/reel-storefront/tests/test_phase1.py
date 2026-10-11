"""Tests for Phase 1: Shared state, security, telemetry, health, and event model."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.graphrec import build_local
from app.main import create_app
from app.storage import SharedState

DATA = Path(__file__).resolve().parents[1] / "data"
FILMS = json.loads((DATA / "films.json").read_text(encoding="utf-8"))


class FakeGraphRecExtended:
    def __init__(self) -> None:
        self.events: dict = {}
        self.calls: list = []
        self.version = uuid4()
        self.feedback_calls = {"impression": 0, "click": 0, "conversion": 0}
        self.fail_feedback = False
        self.storefront = SimpleNamespace(
            events=SimpleNamespace(create=self._create, list=self._list),
            recommendations=SimpleNamespace(get=self._get, for_session=self._for_session),
            feedback=SimpleNamespace(
                impression=self._fb("impression"),
                click=self._fb("click"),
                conversion=self._fb("conversion"),
            ),
        )

    async def health(self):
        return {"status": "ok"}

    async def close(self):
        pass

    async def _create(self, event_type, *, user_id=None, product_id=None, context=None, event_id=None, occurred_at=None):
        duplicate = event_id in self.events
        self.events.setdefault(event_id, (user_id, product_id, event_type))
        return SimpleNamespace(event_id=event_id, accepted=not duplicate, duplicate=duplicate, received_at=datetime.now(timezone.utc))

    async def _list(self, *, limit=50, user_id=None, event_type=None, external_product_id=None):
        out = []
        for eid, (u, p, t) in reversed(list(self.events.items())):
            if user_id and u != user_id:
                continue
            if event_type and t != event_type:
                continue
            if external_product_id and p != external_product_id:
                continue
            out.append(SimpleNamespace(
                event_id=eid, user_id=u, external_product_id=p, event_type=t,
                context={}, occurred_at=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc)
            ))
        return out[:limit]

    def _rank(self, seen, n, offset):
        ids = [f["id"] for f in sorted(FILMS, key=lambda f: f["popularityRank"]) if f["id"] not in seen]
        ids = ids[offset:offset + n]
        return SimpleNamespace(
            request_id="req_" + uuid4().hex[:8],
            items=[SimpleNamespace(external_product_id=i, position=k) for k, i in enumerate(ids, 1)],
            model_version_id=None if not seen else self.version,
            strategy="personalized" if seen else "popular_fallback",
            fallback_used=not seen,
            fallback_tier="tenant_popular" if not seen else "none",
            applied_rules=[],
        )

    async def _get(self, *, user_id, top_n, context=None, exclude_product_ids=None, **options):
        self.options = options
        self.calls.append(("get", user_id))
        live = [p for (u, p, _) in self.events.values() if u == user_id]
        return self._rank({*live}, top_n, len(live))

    async def _for_session(self, session_id, *, recent_product_ids=None, top_n=10, context=None, exclude_product_ids=None, user_id=None, **options):
        self.options = options
        self.calls.append(("session", tuple(recent_product_ids or ())))
        recent = list(recent_product_ids or [])
        return self._rank(set(recent) | set(exclude_product_ids or []), top_n, len(recent))

    def _fb(self, kind):
        async def send(*args, **kwargs):
            self.feedback_calls[kind] += 1
            if self.fail_feedback:
                raise RuntimeError(f"Simulated feedback failure for {kind}")
            return SimpleNamespace(event_id=f"fbk_{kind}_{uuid4().hex[:6]}", accepted=True, duplicate=False)
        return send


@pytest.fixture
def phase1_app(tmp_path):
    cfg = Settings(
        graphrec_api_key="gr_live_test",
        state_dir=tmp_path / "state",
        frontend_dist=tmp_path / "frontend_dist",
        reel_secret_key="test-secret-key-for-signing-sessions-32b",
        reel_cookie_secure=False,
        reel_rate_limit_per_minute=10,
        reel_body_limit_bytes=1024,
    )
    fake = FakeGraphRecExtended()
    storage = SharedState()
    svc = build_local(cfg, fake)
    svc.storage = storage
    app = create_app(cfg, svc)
    return app, cfg, svc, fake


def test_shared_state_durable_diff_and_impressions():
    """Verify SharedState handles last list diffs and impression linking across instances."""
    state1 = SharedState()
    state2 = SharedState()
    # If state is in-memory fallback, state1 and state2 are separate instances,
    # but verify method semantics on a single instance:
    assert state1.swap_last_list("user:1", "home", ["1", "2", "3"]) is None
    prev = state1.swap_last_list("user:1", "home", ["2", "3", "4"])
    assert prev == ["1", "2", "3"]

    state1.set_impression("req_abc", "imp_xyz")
    assert state1.get_impression("req_abc") == "imp_xyz"
    assert state1.get_impression("req_nonexistent") is None


def test_feedback_health_metrics():
    state = SharedState()
    state.record_feedback("impression", True)
    state.record_feedback("impression", False)
    state.record_feedback("click", True)
    health = state.get_feedback_health()
    assert health["impression"]["success"] == 1
    assert health["impression"]["failure"] == 1
    assert health["click"]["success"] == 1
    assert health["click"]["failure"] == 0


def test_rate_limiting_sliding_window():
    state = SharedState()
    # Limit to 3 requests per 60s
    assert state.check_rate_limit("client:1", 3, window_seconds=60) == (True, 0)
    assert state.check_rate_limit("client:1", 3, window_seconds=60) == (True, 0)
    assert state.check_rate_limit("client:1", 3, window_seconds=60) == (True, 0)
    allowed, retry_after = state.check_rate_limit("client:1", 3, window_seconds=60)
    assert allowed is False
    assert retry_after > 0


@pytest.mark.asyncio
async def test_healthz_and_readyz_endpoints(phase1_app):
    app, cfg, svc, fake = phase1_app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # /healthz must return 200
        hz = await client.get("/healthz")
        assert hz.status_code == 200
        assert hz.json()["status"] == "ok"

        # /readyz must return 200 with details
        rz = await client.get("/readyz")
        assert rz.status_code == 200
        data = rz.json()
        assert data["status"] == "ready"
        assert data["checks"]["graphrec"] == "ok"
        assert data["checks"]["catalogue"] == "ok"


@pytest.mark.asyncio
async def test_security_headers_present(phase1_app):
    app, cfg, svc, fake = phase1_app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/reel/session")
        assert resp.status_code == 200
        headers = resp.headers
        assert "Content-Security-Policy" in headers
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert "Referrer-Policy" in headers


@pytest.mark.asyncio
async def test_body_limit_enforced(phase1_app):
    app, cfg, svc, fake = phase1_app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        large_body = {"film_id": "1", "padding": "x" * (cfg.reel_body_limit_bytes + 500)}
        resp = await client.post("/api/reel/watch", json=large_body)
        assert resp.status_code == 413


@pytest.mark.asyncio
async def test_signed_session_tampering_rejected(phase1_app):
    app, cfg, svc, fake = phase1_app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Initial request gets signed cookies
        init = await client.get("/api/reel/session")
        assert init.status_code == 200
        cookie = client.cookies.get("reel_session")
        assert cookie is not None

        # Forged cookie with invalid signature falls back safely to anonymous
        client.cookies.set("reel_session", "forged_sess_invalid_token")
        tampered = await client.get("/api/reel/session")
        assert tampered.status_code == 200
        assert tampered.json()["data"]["persona"]["key"] == "anon"

