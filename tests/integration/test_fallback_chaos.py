"""NR-NF-08 / ER-F-10: the recommendation fallback chain under failures, alone and combined.

Each row of the matrix states what must still happen when a dependency is down:

| Qdrant | Redis | model artifact | catalog | expected                                              |
|--------|-------|----------------|---------|-------------------------------------------------------|
| up     | up    | ok             | items   | 200 personalized (DGSR via Qdrant)                    |
| down   | up    | ok             | items   | 200 personalized (DGSR item table scored in-process)  |
| up     | down  | ok             | items   | 200 personalized (admission fails open, reported)     |
| down   | down  | ok             | items   | 200 personalized                                      |
| down   | down  | missing        | items   | 200 popular_fallback, no model_version_id claimed     |
| any    | any   | none active    | items   | 200 popular_fallback                                  |
| down   | down  | missing        | empty   | 200 with no items, or 503 when fallback is not allowed|
"""
from __future__ import annotations

import shutil
from uuid import UUID

import pytest

from graphrec_core.database.models import TrainingJob
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.dgsr.serving import evict_artifact
from graphrec_core.dgsr.worker import run_once
from graphrec_core.settings import get_settings
from graphrec_core.usage import admission as admission_module
from tests.integration.test_training_worker import isolated_training_queue  # noqa: F401  (autouse fixture)
from tests.integration.test_xr_features import operator, provision, seed_trainable

pytestmark = pytest.mark.integration


@pytest.fixture
def trained(client, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'generated_model_root', str(tmp_path))
    monkeypatch.setattr(get_settings(), 'training_cooldown_seconds', 0)
    tenant, headers = provision(client)
    operator(client, tenant, training_jobs=5)
    seed_trainable(client, headers)
    job = client.post('/v1/training-jobs', json={'request_id': 'chaos', 'configuration': {'mode': 'train', 'epochs': 1}},
                      headers=headers)
    assert job.status_code == 200, job.text
    assert run_once()
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        done = db.get(TrainingJob, UUID(job.json()['id']))
        assert done.status == 'succeeded', done.failure_reason
        version = str(done.model_version_id)
    assert client.post(f'/v1/model-versions/{version}:activate', headers=headers).status_code == 200
    return tenant, headers, version, tmp_path


@pytest.fixture
def qdrant_down(monkeypatch):
    def unreachable():
        raise ConnectionError('qdrant unreachable (chaos test)')
    monkeypatch.setattr('apps.api.routes.recommendations.get_qdrant_client', unreachable)


@pytest.fixture
def redis_down():
    healthy = admission_module.get_admission()
    admission_module.set_admission(admission_module.AdmissionController('redis://127.0.0.1:1/0', timeout_ms=30))
    yield
    admission_module.set_admission(healthy)


def recommend(client, headers, **extra):
    return client.post('/v1/recommendations', json={'user_id': 'u0', 'top_n': 3, **extra}, headers=headers)


def remove_artifact(tmp_path, tenant):
    for directory in (tmp_path / tenant).iterdir():
        evict_artifact(directory)
    shutil.rmtree(tmp_path / tenant)


def test_nr_nf_08_healthy_baseline_is_personalized(client, trained):
    tenant, headers, version, _ = trained
    body = recommend(client, headers).json()
    assert body['strategy'] == 'personalized' and body['model_version_id'] == version
    # u0 has seen p0-p5 and p8 has no interactions (not in the model's vocabulary): only p6 and p7 remain.
    assert sorted(i['external_product_id'] for i in body['items']) == ['p6', 'p7']


def test_nr_nf_08_qdrant_down_scores_in_process(client, trained, qdrant_down):
    _, headers, version, _ = trained
    response = recommend(client, headers)
    assert response.status_code == 200, response.text
    assert response.json()['strategy'] == 'personalized' and response.json()['model_version_id'] == version


def test_nr_nf_08_redis_down_fails_open_and_reports_it(client, trained, redis_down):
    _, headers, _, _ = trained
    assert recommend(client, headers).json()['strategy'] == 'personalized'
    assert client.get('/v1/deployment', headers=headers).json()['rate_limiter']['status'] == 'degraded'


def test_nr_nf_08_qdrant_and_redis_down_still_personalized(client, trained, qdrant_down, redis_down):
    _, headers, _, _ = trained
    response = recommend(client, headers)
    assert response.status_code == 200 and response.json()['strategy'] == 'personalized'


def test_nr_nf_08_everything_down_and_artifact_lost_serves_popular_without_claiming_a_model(
        client, trained, qdrant_down, redis_down):
    tenant, headers, version, tmp_path = trained
    remove_artifact(tmp_path, tenant)
    body = recommend(client, headers).json()
    assert body['strategy'] == 'popular_fallback' and body['fallback_used'] is True
    assert body['model_version_id'] is None and body['active_model_version_id'] == version
    assert body['items'][0]['external_product_id'] == 'p0'   # the most popular product in the seed


def test_nr_nf_08_no_active_model_serves_popular(client):
    tenant, headers = provision(client)
    seed_trainable(client, headers)
    body = recommend(client, headers).json()
    assert body['strategy'] == 'popular_fallback' and body['model_version_id'] is None and body['items']


def test_nr_nf_08_empty_catalog_under_full_outage(client, trained, qdrant_down, redis_down):
    tenant, headers, _, tmp_path = trained
    remove_artifact(tmp_path, tenant)
    for i in range(9):
        assert client.post(f'/v1/products/p{i}:disable', json={}, headers=headers).status_code == 200
    allowed = recommend(client, headers)
    assert allowed.status_code == 200 and allowed.json()['items'] == []
    refused = recommend(client, headers, fallback_allowed=False)
    assert refused.status_code == 503 and refused.json()['error']['code'] == 'recommendation_unavailable'
    assert refused.json()['error']['retryable'] in (True, False) and refused.headers.get('x-correlation-id')
