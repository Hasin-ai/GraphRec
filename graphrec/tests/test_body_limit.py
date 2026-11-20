"""A-18: chunked bodies are bounded like bodies with a Content-Length."""
from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from graphrec_core.settings import get_settings


def _chunks(total: int, size: int = 4096):
    sent = 0
    while sent < total:
        part = min(size, total - sent)
        sent += part
        yield b"x" * part


def test_nr_nf_03_chunked_body_over_limit_is_rejected_before_parsing():
    limit = get_settings().max_request_body_bytes
    with TestClient(app) as client:
        response = client.post("/v1/auth/login", content=_chunks(limit + 10),
                               headers={"Content-Type": "application/json", "Accept": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_chunked_body_within_limit_still_reaches_the_route():
    with TestClient(app) as client:
        body = b'{"email": "nobody@example.org", "password": "wrong-password-123"}'
        response = client.post("/v1/auth/login", content=iter([body[:10], body[10:]]),
                               headers={"Content-Type": "application/json", "Accept": "application/json"})
    assert response.status_code in {401, 429}


def test_identical_denial_audits_are_bounded_per_minute():
    from types import SimpleNamespace
    from uuid import uuid4

    from apps.api.errors import DENIAL_AUDITS_PER_MINUTE, _denial_audit_admitted

    principal = SimpleNamespace(tenant_id=uuid4(), actor_reference=uuid4())
    results = [_denial_audit_admitted(principal, "rate_limit_exceeded", "/v1/recommendations") for _ in range(20)]
    assert results.count(True) == DENIAL_AUDITS_PER_MINUTE
    # A different reason is recorded independently.
    assert _denial_audit_admitted(principal, "insufficient_scope", "/v1/recommendations")
