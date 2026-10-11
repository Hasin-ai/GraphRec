"""A-03 / NR-NF-03 / NR-NF-06: every failure uses the documented error envelope."""
from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.main import app


def test_nr_nf_06_unhandled_error_returns_envelope_with_correlation_id(monkeypatch):
    from apps.api.routes import tenants

    def boom(self, *args, **kwargs):  # noqa: ANN001
        raise RuntimeError("secret detail that must not leak")

    monkeypatch.setattr(tenants.RegistrationService, "register", boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/tenants",
            json={"name": "Envelope Test", "admin_email": "a@example.org"},
            headers={"Idempotency-Key": "k" * 20, "Accept": "application/json"},
        )
    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "internal_error" and body["retryable"] is True
    assert UUID(body["correlation_id"]) == UUID(response.headers["X-Correlation-ID"])
    assert "secret detail" not in response.text


def test_nr_nf_03_method_not_allowed_is_not_reported_as_malformed():
    with TestClient(app) as client:
        response = client.delete("/v1/auth/login", headers={"Accept": "application/json"})
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert "X-Correlation-ID" in response.headers
