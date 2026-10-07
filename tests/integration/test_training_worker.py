from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select, text

from graphrec_core.database.models import TrainingJob
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.dgsr.worker import run_once
from graphrec_core.settings import get_settings
from tests.integration.test_srs_acceptance import provision, limits

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def isolated_training_queue():
    """A-16: claim_training_job() takes the globally oldest queued job, so jobs
    left queued by other tests (any tenant) would be claimed here instead of the
    job under test. Drain them first through the same claim path and mark them
    cancelled, tenant by tenant, so these tests see only their own work."""
    while True:
        with SessionLocal() as db, db.begin():
            claimed = db.execute(text('SELECT * FROM public.claim_training_job()')).first()
        if claimed is None:
            break
        with SessionLocal() as db, db.begin():
            job_id, tenant_id = claimed
            set_local_tenant(db, tenant_id)
            job = db.get(TrainingJob, job_id)
            job.status = job.stage = 'cancelled'
            job.completed_at = datetime.now(timezone.utc)
    yield


def test_interrupted_job_retries_once_then_fails_visibly(client):
    tenant, headers = provision(client)
    seed(client, headers)
    response = client.post('/v1/training-jobs', json={'configuration': {'epochs': 1}}, headers=headers)
    assert response.status_code == 200, response.text
    job_id = UUID(response.json()['id'])
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        job = db.get(TrainingJob, job_id)
        job.status = 'running'
        job.attempts = 1
        job.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    with SessionLocal() as db, db.begin():
        claimed = db.execute(text('SELECT * FROM public.claim_training_job()')).first()
        assert claimed and claimed.job_id == job_id
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        job = db.get(TrainingJob, job_id)
        assert job.status == 'running' and job.attempts == 2
        job.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    with SessionLocal() as db, db.begin():
        assert db.execute(text('SELECT * FROM public.claim_training_job()')).first() is None
    status = client.get('/v1/training-jobs', headers=headers)
    assert status.status_code == 200
    failed = next(job for job in status.json()['items'] if job['id'] == str(job_id))
    assert failed['status'] == 'failed'
    assert 'retry budget exhausted' in failed['failure_reason']


def seed(client, headers):
    products = [{'external_id': str(i), 'title': f'Movie {i}', 'category': 'Drama' if i % 2 else 'Comedy'} for i in range(12)]
    assert client.post('/v1/products:bulk-upsert', json={'products': products}, headers=headers).status_code == 200
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [{'event_id': f'{u}-{i}', 'event_type': 'view', 'user_id': str(u),
        'external_product_id': str((i + u) % 12), 'occurred_at': (start + timedelta(seconds=u * 20 + i)).isoformat()}
        for u in range(3) for i in range(8)]
    assert client.post('/v1/events/batches', json={'events': events}, headers=headers).status_code == 200


def test_real_tenant_training_and_cancel(client, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'generated_model_root', str(tmp_path))
    tenant, headers = provision(client)
    limits(client, tenant, training_jobs=3)
    seed(client, headers)
    request = {'request_id': 'real-train', 'configuration': {'mode': 'train', 'epochs': 1}}
    response = client.post('/v1/training-jobs', json=request, headers=headers)
    assert response.status_code == 200, response.text
    job = response.json()
    assert job['status'] == 'queued' and job['dataset_snapshot_id']
    assert client.post('/v1/training-jobs', json=request, headers=headers).json()['id'] == job['id']
    assert run_once()
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        completed = db.get(TrainingJob, UUID(job['id']))
        assert completed.status == 'succeeded', completed.failure_reason
        assert completed.progress == 100
        version_id = completed.model_version_id
    version = client.get(f'/v1/model-versions/{version_id}', headers=headers).json()
    assert version['metrics']['test']['examples'] == 3
    assert 0 <= version['metrics']['test']['NDCG@10'] <= 1
    assert version['metrics']['source']['tenant_id'] == tenant
    activation = client.post(f'/v1/model-versions/{version_id}:activate', headers=headers)
    assert activation.status_code == 200, activation.text
    served = client.post('/v1/recommendations', json={'user_id': '0', 'top_n': 2}, headers=headers)
    assert served.status_code == 200, served.text
    assert served.json()['strategy'] == 'personalized'
    assert len(served.json()['items']) == 2
    _, foreign = provision(client)
    seed(client, foreign)
    copied = client.post('/v1/model-versions', json={'version_tag': 'foreign-artifact', 'model_type': 'dgsr',
        'artifact_uri': version['artifact_uri'], 'metrics': version['metrics']}, headers=foreign)
    assert copied.status_code == 200, copied.text
    assert client.post(f"/v1/model-versions/{copied.json()['id']}:activate", headers=foreign).status_code == 422
    cooldown = client.post('/v1/training-jobs', json={**request, 'request_id': 'too-soon'}, headers=headers)
    assert cooldown.status_code == 409, cooldown.text
    assert cooldown.json()['error']['code'] == 'training_cooldown'
    assert cooldown.json()['error']['retryable'] is True
    assert int(cooldown.headers['Retry-After']) > 0
    monkeypatch.setattr(get_settings(), 'training_cooldown_seconds', 0)
    cancel = client.post('/v1/training-jobs', json={**request, 'request_id': 'cancel-train'}, headers=headers)
    assert cancel.status_code == 200, cancel.text
    job_id = cancel.json()['id']
    cancelled = client.post(f'/v1/training-jobs/{job_id}:cancel', headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()['status'] == 'cancelled'
    # UC-14: a terminal (already cancelled) job returns a state conflict.
    repeat = client.post(f'/v1/training-jobs/{job_id}:cancel', headers=headers)
    assert repeat.status_code == 409 and repeat.json()['error']['code'] == 'job_terminal'
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        assert db.scalar(select(TrainingJob.model_version_id).where(TrainingJob.id == UUID(job_id))) is None
