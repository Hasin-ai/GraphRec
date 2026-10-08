"""ER-NF-09: Prometheus metrics and structured JSON logs."""
from __future__ import annotations

import json
import logging

import pytest

from graphrec_core.observability import JsonFormatter, correlation_id_var
from graphrec_core.settings import get_settings
from tests.integration.test_srs_acceptance import provision

pytestmark = pytest.mark.integration


def test_er_nf_09_metrics_count_requests_by_route_template_without_tenant_data(client):
    tenant, headers = provision(client)
    client.put("/v1/products/secret-sku-123", json={"external_id": "secret-sku-123", "title": "P"}, headers=headers)
    client.get("/v1/products/secret-sku-123", headers=headers)
    body = client.get("/metrics").text
    assert 'graphrec_http_requests_total{method="GET",route="/v1/products/{external_id}",status="2xx"}' in body
    assert 'graphrec_http_request_duration_seconds_bucket{route="/v1/products/{external_id}",le="+Inf"}' in body
    assert "graphrec_database_up 1" in body and "graphrec_training_jobs{status=\"queued\"}" in body
    assert 'graphrec_build_info{version="' in body
    # Route templates only: no tenant id or product id ever becomes a label value.
    assert tenant not in body and "secret-sku-123" not in body


def test_er_nf_09_metrics_require_the_token_when_configured(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_token", "m" * 40)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer " + "x" * 40}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer " + "m" * 40}).status_code == 200


def test_er_nf_09_metrics_are_disabled_in_production_without_a_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "graphrec_env", "production")
    assert client.get("/metrics").status_code == 404


def test_er_nf_09_json_logs_carry_the_correlation_id():
    token = correlation_id_var.set("c0ffee00-0000-4000-8000-000000000001")
    try:
        record = logging.LogRecord("graphrec.request", logging.INFO, __file__, 1, "GET %s", ("/v1/x",), None)
        record.route, record.status = "/v1/x", 200
        line = json.loads(JsonFormatter().format(record))
    finally:
        correlation_id_var.reset(token)
    assert line["message"] == "GET /v1/x" and line["level"] == "info" and line["status"] == 200
    assert line["correlation_id"] == "c0ffee00-0000-4000-8000-000000000001"


def test_er_nf_09_unknown_methods_and_malformed_keys_cannot_grow_or_break_metrics():
    from graphrec_core.observability import Metrics
    metrics = Metrics()
    for method in ("FOO", "A|B", "GET"):
        metrics.observe(method, "/v1/x", 200, 0.01)
    data, _ = metrics.snapshot()
    assert {k.split("|")[1] for k in data if k.startswith("req|")} == {"GET", "OTHER"}
    metrics._local["req|broken"] = 1   # a malformed key from an older process
    assert "graphrec_http_requests_total" in metrics.render(None, {})
