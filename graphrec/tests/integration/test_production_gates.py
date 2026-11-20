"""A-02: development-only model paths are unavailable in production."""
from __future__ import annotations

import pytest

from graphrec_core.settings import get_settings
from tests.integration.test_srs_acceptance import provision

pytestmark = pytest.mark.integration


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(get_settings(), "graphrec_env", "production")


def test_manual_model_registration_is_hidden_in_production(client, production):
    _, headers = provision(client)
    response = client.post("/v1/model-versions", headers=headers,
                           json={"version_tag": "claimed", "model_type": "dgsr", "metrics": {"NDCG@10": 0.99}})
    assert response.status_code == 404
    assert client.get("/v1/model-versions", headers=headers).json()["items"] == []


def test_placeholder_training_is_rejected_in_production(client, production):
    _, headers = provision(client)
    response = client.post("/v1/training-jobs", headers=headers, json={"configuration": {"mode": "placeholder"}})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["field"] == "configuration.mode"
    assert client.get("/v1/training-jobs", headers=headers).json()["items"] == []


def test_development_still_allows_placeholders(client):
    _, headers = provision(client)
    response = client.post("/v1/model-versions", headers=headers,
                           json={"version_tag": "dev-only", "model_type": "development_placeholder"})
    assert response.status_code == 200
    assert response.json()["artifact_uri"].startswith("unregistered://")
