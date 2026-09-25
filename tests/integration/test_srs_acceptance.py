from uuid import UUID, uuid4
import hashlib
import json

import pytest

from graphrec_core.settings import get_settings
from graphrec_core.database.models import AuditLog, DatasetSnapshotContent
from sqlalchemy import select
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant

pytestmark = pytest.mark.integration


def provision(client):
    tag = uuid4().hex
    created = client.post('/v1/tenants', json={'name': f'SRS {tag}', 'admin_email': f'{tag}@example.org'},
                          headers={'Accept': 'application/json', 'Idempotency-Key': tag})
    assert created.status_code == 201, created.text
    auth = client.post('/v1/auth/setup-password', json={'setup_token': created.json()['setup_token'], 'password': f'Test-{tag}!'}, headers={'Accept': 'application/json'})
    assert auth.status_code == 200, auth.text
    return created.json()['id'], {'Accept': 'application/json', 'Authorization': f"Bearer {auth.json()['access_token']}"}


def limits(client, tenant, **overrides):
    response = client.post(f'/v1/platform/tenants/{tenant}/quotas', json={'overrides': overrides},
        headers={'Accept': 'application/json', 'Authorization': f'Bearer {get_settings().platform_admin_token}'})
    assert response.status_code == 200, response.text


def test_feedback_replay_ownership_and_disabled_recommendation(client):
    tenant, headers = provision(client)
    _, foreign = provision(client)
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=headers).status_code == 200
    request = {'request_id': 'same-request', 'top_n': 1}
    result = client.post('/v1/recommendations', json=request, headers=headers)
    assert result.status_code == 200, result.text
    assert client.post('/v1/recommendations', json=request, headers=headers).json() == result.json()
    feedback = {'event_id': 'same-impression', 'request_id': result.json()['request_id'], 'items': result.json()['items']}
    assert client.post('/v1/feedback/impressions', json=feedback, headers=headers).json()['duplicate'] is False
    assert client.post('/v1/feedback/impressions', json=feedback, headers=headers).json()['duplicate'] is True
    assert client.post('/v1/feedback/impressions', json=feedback, headers=foreign).status_code == 404
    changed = {**feedback, 'context': {'changed': True}}
    assert client.post('/v1/feedback/impressions', json=changed, headers=headers).status_code == 409
    assert client.post('/v1/products/movie:disable', headers=headers).status_code == 200
    assert client.post('/v1/recommendations', json=request, headers=headers).status_code == 409
    assert client.post('/v1/recommendations', json={'top_n': 1}, headers=headers).json()['items'] == []


def test_limits_and_snapshot_ownership_are_enforced_by_api(client):
    tenant, headers = provision(client)
    _, foreign = provision(client)
    limits(client, tenant, stored_products=1, accepted_events=1, recommendation_requests=1, training_jobs=0)
    product = {'external_id': 'one', 'title': 'One'}
    assert client.put('/v1/products/one', json=product, headers=headers).status_code == 200
    assert client.put('/v1/products/two', json={**product, 'external_id': 'two'}, headers=headers).status_code == 429
    assert client.post('/v1/products:bulk-upsert', json={'products': [{**product, 'external_id': 'two'}]}, headers=headers).status_code == 429
    assert client.put('/v1/products/one', json={**product, 'title': 'Updated'}, headers=headers).status_code == 200
    event = {'event_id': 'one', 'event_type': 'view', 'user_id': 'shopper', 'external_product_id': 'one'}
    assert client.post('/v1/events', json={**event, 'external_product_id': 'foreign'}, headers=headers).status_code == 422
    assert client.post('/v1/events', json=event, headers=headers).status_code == 200
    assert client.post('/v1/events', json=event, headers=headers).json()['duplicate'] is True
    assert client.post('/v1/events/batches', json={'events': [{**event, 'event_id': 'two'}]}, headers=headers).status_code == 429
    request = {'request_id': 'meter-once'}
    assert client.post('/v1/recommendations', json=request, headers=headers).status_code == 200
    assert client.post('/v1/recommendations', json=request, headers=headers).status_code == 200
    assert client.post('/v1/recommendations', json={}, headers=headers).status_code == 429
    assert client.post('/v1/training-jobs', json={}, headers=headers).status_code == 429
    snapshot = client.post('/v1/datasets/snapshots', json={}, headers=foreign)
    assert snapshot.status_code == 200, snapshot.text
    assert client.post('/v1/training-jobs', json={'dataset_snapshot_id': snapshot.json()['id']}, headers=headers).status_code == 404


def test_snapshot_captures_real_immutable_tenant_content(client):
    tenant, headers = provision(client)
    foreign_tenant, _ = provision(client)
    product = {'external_id': 'snapshot-movie', 'title': 'Original title'}
    assert client.put('/v1/products/snapshot-movie', json=product, headers=headers).status_code == 200
    response = client.post('/v1/datasets/snapshots', json={}, headers=headers)
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot['artifact_uri'].startswith('postgres://dataset_snapshot_contents/')
    assert client.put('/v1/products/snapshot-movie', json={**product, 'title': 'Changed'}, headers=headers).status_code == 200
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        stored = db.get(DatasetSnapshotContent, UUID(snapshot['id']))
        assert stored.content['products'][0]['title'] == 'Original title'
        canonical = json.dumps(stored.content, sort_keys=True, separators=(',', ':')).encode()
        assert hashlib.sha256(canonical).hexdigest() == snapshot['checksum']
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(foreign_tenant))
        assert db.get(DatasetSnapshotContent, UUID(snapshot['id'])) is None


def test_training_replays_once_and_failed_activation_is_audited(client):
    tenant, headers = provision(client)
    limits(client, tenant, training_jobs=1)
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=headers).status_code == 200
    request = {'request_id': 'train-once', 'configuration': {'mode': 'placeholder'}}
    response = client.post('/v1/training-jobs', json=request, headers=headers)
    assert response.status_code == 200, response.text
    replay = client.post('/v1/training-jobs', json=request, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()['id'] == response.json()['id']
    assert client.post('/v1/training-jobs', json={**request, 'configuration': {'changed': True}}, headers=headers).status_code == 409
    assert client.post('/v1/training-jobs', json={'request_id': 'second'}, headers=headers).status_code == 429
    version = response.json()['model_version_id']
    assert client.post(f'/v1/model-versions/{version}:activate', headers=headers).status_code == 200
    bad = client.post('/v1/model-versions', json={'version_tag': 'missing', 'model_type': 'dgsr', 'artifact_uri': 'file:///artifacts/missing'}, headers=headers)
    assert bad.status_code == 200, bad.text
    failure = client.post(f"/v1/model-versions/{bad.json()['id']}:activate", headers=headers)
    assert failure.status_code == 422, failure.text
    assert client.get('/v1/deployment', headers=headers).json()['active_model_version_id'] == version
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        audits = list(db.scalars(select(AuditLog).where(AuditLog.action_type == 'model_activation')))
        assert {a.outcome for a in audits} == {'succeeded', 'failed'}
        assert all(a.actor_type == 'tenant_user' and a.actor_reference for a in audits)
        assert any(str(a.correlation_reference) == failure.headers['x-correlation-id'] for a in audits)


def test_platform_plan_assignment_preserves_overrides_and_usage(client):
    tenant, headers = provision(client)
    operator = {'Accept': 'application/json', 'Authorization': f'Bearer {get_settings().platform_admin_token}'}
    limits(client, tenant, stored_products=7)
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=headers).status_code == 200
    plans = client.get('/v1/platform/plans', headers=operator).json()
    pro = next(plan for plan in plans if plan['code'] == 'pro')
    response = client.post(f'/v1/platform/tenants/{tenant}/plan', json={'plan_id': pro['id']}, headers=operator)
    assert response.status_code == 200, response.text
    assert response.json()['plan_code'] == 'pro'
    assert response.json()['limits']['stored_products'] == 7
    assert response.json()['limits']['training_jobs'] == pro['limits']['training_jobs']
    current = client.get(f'/v1/platform/tenants/{tenant}/quotas', headers=operator)
    assert current.json() == response.json()
    assert client.get(f'/v1/platform/tenants/{tenant}/quotas', headers=headers).status_code == 401
    assert client.post(f'/v1/platform/tenants/{tenant}/quotas', json={'overrides': {'stored_products': -1}}, headers=operator).status_code == 422
    assert client.get('/v1/products', headers=headers).json()['total'] == 1


def test_concurrency_and_minute_limits_reject_excess_without_double_metering(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from apps.api.routes import recommendations
    tenant, headers = provision(client)
    limits(client, tenant, concurrent_recommendation_requests=1, requests_per_minute=1)
    entered, release = Event(), Event()
    original = recommendations._serve

    def slow(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(recommendations, '_serve', slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, '/v1/recommendations', json={'request_id': 'slow'}, headers=headers)
        try:
            assert entered.wait(5)
            blocked = client.post('/v1/recommendations', json={}, headers=headers)
            assert blocked.status_code == 429, blocked.text
            assert blocked.json()['error']['details']['limit_name'] == 'concurrent_recommendation_requests'
        finally:
            release.set()
        assert pending.result().status_code == 200
    assert client.post('/v1/recommendations', json={'request_id': 'slow'}, headers=headers).status_code == 200
    rate = client.post('/v1/recommendations', json={}, headers=headers)
    assert rate.status_code == 429
    assert rate.json()['error']['details']['limit_name'] == 'requests_per_minute'
    assert rate.headers['retry-after'] == '60'
