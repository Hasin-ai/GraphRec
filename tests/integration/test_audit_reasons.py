"""ER-F-11 / UC-27 / UC-31 (A-09): reasons are recorded and the audit trail is searchable."""
from __future__ import annotations

import pytest

from graphrec_core.settings import get_settings
from tests.integration.test_srs_acceptance import provision

pytestmark = pytest.mark.integration


def _operator():
    return {"Accept": "application/json", "Authorization": f"Bearer {get_settings().platform_admin_token}"}


def test_er_f_11_tenant_status_change_requires_and_records_a_reason(client):
    tenant, _ = provision(client)
    missing = client.post(f"/v1/platform/tenants/{tenant}/status", json={"status": "suspended"}, headers=_operator())
    assert missing.status_code == 422
    changed = client.post(f"/v1/platform/tenants/{tenant}/status", headers=_operator(),
                          json={"status": "suspended", "reason": "Chargeback investigation #42"})
    assert changed.status_code == 200, changed.text
    audit = client.get("/v1/platform/audit", params={"tenant_id": tenant, "action": "tenant.status_changed"},
                       headers=_operator()).json()["items"]
    assert [a["reason"] for a in audit] == ["Chargeback investigation #42"]
    assert audit[0]["correlation_reference"] == changed.headers["X-Correlation-ID"]


def test_er_f_11_plan_and_quota_changes_record_reasons(client):
    tenant, _ = provision(client)
    pro = next(p for p in client.get("/v1/platform/plans", headers=_operator()).json() if p["code"] == "pro")
    assert client.post(f"/v1/platform/tenants/{tenant}/plan", headers=_operator(),
                       json={"plan_id": pro["id"], "reason": "Upgrade approved by sales"}).status_code == 200
    assert client.post(f"/v1/platform/tenants/{tenant}/quotas", headers=_operator(),
                       json={"overrides": {"training_jobs": 20}, "reason": "Pilot extension"}).status_code == 200
    reasons = {a["action_type"]: a["reason"] for a in client.get(
        "/v1/platform/audit", params={"tenant_id": tenant}, headers=_operator()).json()["items"] if a["reason"]}
    assert "Upgrade approved by sales" in reasons.values()
    assert "Pilot extension" in reasons.values()


def test_er_f_11_activation_reason_is_audited_even_when_activation_fails(client):
    tenant, headers = provision(client)
    version = client.post("/v1/model-versions", headers=headers,
                          json={"version_tag": "unindexed", "model_type": "development_placeholder"}).json()["id"]
    failed = client.post(f"/v1/model-versions/{version}:activate", json={"reason": "Spring campaign"}, headers=headers)
    assert failed.status_code == 422
    audit = client.get("/v1/platform/audit", params={"tenant_id": tenant, "action": "model_activation"},
                       headers=_operator()).json()["items"]
    assert audit and audit[0]["outcome"] == "failed" and audit[0]["reason"] == "Spring campaign"


def test_uc_31_audit_pagination_and_time_filters(client):
    tenant, _ = provision(client)
    for status in ("suspended", "active", "suspended", "active"):
        client.post(f"/v1/platform/tenants/{tenant}/status", json={"status": status, "reason": f"step {status}"},
                    headers=_operator())
    first = client.get("/v1/platform/audit", params={"tenant_id": tenant, "action": "tenant.status_changed",
                                                     "limit": 3}, headers=_operator()).json()
    assert len(first["items"]) == 3 and first["next_before"]
    rest = client.get("/v1/platform/audit", params={"tenant_id": tenant, "action": "tenant.status_changed",
                                                    "before": first["next_before"]}, headers=_operator()).json()
    assert len(rest["items"]) == 1 and rest["next_before"] is None
    future = client.get("/v1/platform/audit", params={"since": "2999-01-01T00:00:00Z"}, headers=_operator()).json()
    assert future["items"] == []
