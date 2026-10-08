from uuid import UUID, uuid4
import hashlib
import json

import pytest

from graphrec_core.settings import get_settings
from graphrec_core.database.models import AuditLog, Customer, DatasetSnapshotContent, RecommendationFeedback, RecommendationRecord, RecommendationResult
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
    """NR-F-14 / UC-23 / BRULE-09 / BRULE-11."""
    tenant, headers = provision(client)
    provisioned_foreign_tenant, foreign = provision(client)
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=headers).status_code == 200
    assert client.post('/v1/recommendations', json={'top_n': 1}, headers=headers).status_code == 422
    assert client.post('/v1/recommendations', json={'user_id': ' ', 'context': {'session_id': 'session'}}, headers=headers).status_code == 422
    unavailable = client.post('/v1/recommendations', json={'user_id': 'shopper', 'fallback_allowed': False}, headers=headers)
    assert unavailable.status_code == 503
    assert unavailable.json()['error']['code'] == 'recommendation_unavailable'
    # BRULE-03 (A-21b): the customer exists because the tenant sent an interaction for it;
    # recommendation requests alone never create customers.
    assert client.post('/v1/events', json={'event_id': 'shopper-view', 'event_type': 'view', 'user_id': 'shopper',
                                           'external_product_id': 'movie'}, headers=headers).status_code == 200
    request = {'request_id': 'same-request', 'user_id': 'shopper', 'top_n': 1}
    result = client.post('/v1/recommendations', json=request, headers=headers)
    assert result.status_code == 200, result.text
    assert client.post('/v1/recommendations', json=request, headers=headers).json() == result.json()
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        ranked = db.scalars(select(RecommendationResult).where(
            RecommendationResult.tenant_id == UUID(tenant),
            RecommendationResult.request_id == result.json()['request_id'],
        )).all()
        assert [(row.external_product_id, row.rank_position) for row in ranked] == [('movie', 1)]
        ranked_id = ranked[0].id
        assert db.get(RecommendationRecord, (UUID(tenant), result.json()['request_id'])).external_customer_id == 'shopper'
        customer_id = db.scalar(select(Customer.id).where(Customer.tenant_id == UUID(tenant), Customer.external_id == 'shopper'))
        assert customer_id
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(provisioned_foreign_tenant))
        assert db.get(Customer, customer_id) is None
    feedback = {'event_id': 'same-impression', 'request_id': result.json()['request_id'], 'items': result.json()['items']}
    assert client.post('/v1/feedback/impressions', json=feedback, headers=headers).json()['duplicate'] is False
    assert client.post('/v1/feedback/impressions', json=feedback, headers=headers).json()['duplicate'] is True
    assert client.post('/v1/feedback/impressions', json=feedback, headers=foreign).status_code == 404
    changed = {**feedback, 'context': {'changed': True}}
    assert client.post('/v1/feedback/impressions', json=changed, headers=headers).status_code == 409
    click = {'event_id': 'same-click', 'request_id': result.json()['request_id'],
             'external_product_id': 'movie', 'position': 1, 'impression_event_id': 'same-impression'}
    assert client.post('/v1/feedback/clicks', json=click, headers=headers).status_code == 200
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        stored_click = db.get(RecommendationFeedback, (UUID(tenant), 'same-click'))
        assert stored_click.recommendation_result_id == ranked_id
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(provisioned_foreign_tenant))
        assert db.get(RecommendationResult, ranked_id) is None
    assert client.post('/v1/products/movie:disable', headers=headers).status_code == 200
    assert client.post('/v1/recommendations', json=request, headers=headers).status_code == 409
    assert client.post('/v1/recommendations', json={'user_id': 'shopper', 'top_n': 1}, headers=headers).json()['items'] == []


def test_limits_and_snapshot_ownership_are_enforced_by_api(client):
    """ER-F-09 / BRULE-10."""
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
    request = {'request_id': 'meter-once', 'user_id': 'shopper'}
    assert client.post('/v1/recommendations', json=request, headers=headers).status_code == 200
    assert client.post('/v1/recommendations', json=request, headers=headers).status_code == 200
    assert client.post('/v1/recommendations', json={'user_id': 'shopper'}, headers=headers).status_code == 429
    assert client.post('/v1/training-jobs', json={}, headers=headers).status_code == 429
    snapshot = client.post('/v1/datasets/snapshots', json={}, headers=foreign)
    assert snapshot.status_code == 200, snapshot.text
    assert client.post('/v1/training-jobs', json={'dataset_snapshot_id': snapshot.json()['id']}, headers=headers).status_code == 404


def test_snapshot_captures_real_immutable_tenant_content(client):
    """ER-F-01 / BRULE-12."""
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
    """ER-F-06 / UC-18 / ER-NF-03."""
    tenant, headers = provision(client)
    _, foreign = provision(client)
    limits(client, tenant, training_jobs=1)
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=headers).status_code == 200
    request = {'request_id': 'train-once', 'configuration': {'mode': 'placeholder'}}
    response = client.post('/v1/training-jobs', json=request, headers=headers)
    assert response.status_code == 200, response.text
    assert client.get(f"/v1/training-jobs/{response.json()['id']}", headers=headers).json()['id'] == response.json()['id']
    assert client.get(f"/v1/training-jobs/{response.json()['id']}", headers=foreign).status_code == 404
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
    deployment = client.get('/v1/deployment', headers=headers).json()
    assert deployment['active_model_version_id'] == version
    assert deployment['desired_model_version_id'] == bad.json()['id']
    assert deployment['status'] == 'degraded' and deployment['ready_capacity'] == 1
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        audits = list(db.scalars(select(AuditLog).where(AuditLog.action_type == 'model_activation')))
        assert {a.outcome for a in audits} == {'succeeded', 'failed'}
        assert all(a.actor_type == 'tenant_user' and a.actor_reference for a in audits)
        assert any(str(a.correlation_reference) == failure.headers['x-correlation-id'] for a in audits)


def test_deployment_tracks_last_ready_version_and_protects_rollback_target(client):
    """NR-F-11 / UC-19 / XR-F-05 / XR-NF-01 / UC-25."""
    tenant, headers = provision(client)
    limits(client, tenant, training_jobs=3)
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=headers).status_code == 200
    first = client.post('/v1/training-jobs', json={'configuration': {'mode': 'placeholder'}}, headers=headers)
    second = client.post('/v1/training-jobs', json={'configuration': {'mode': 'placeholder'}}, headers=headers)
    assert first.status_code == second.status_code == 200
    first_id, second_id = first.json()['model_version_id'], second.json()['model_version_id']
    assert client.post(f'/v1/model-versions/{first_id}:activate', headers=headers).status_code == 200
    assert client.post(f'/v1/model-versions/{second_id}:activate', headers=headers).status_code == 200
    deployment = client.get('/v1/deployment', headers=headers).json()
    assert deployment['active_model_version_id'] == second_id
    assert deployment['desired_model_version_id'] == second_id
    assert deployment['ready_capacity'] == deployment['desired_capacity'] == 1
    assert client.post(f'/v1/model-versions/{first_id}:archive', headers=headers).status_code == 409
    restored = client.post(f'/v1/models/{first_id}:rollback', headers=headers)
    assert restored.status_code == 200, restored.text
    assert client.get('/v1/deployment', headers=headers).json()['active_model_version_id'] == first_id


def test_platform_plan_assignment_preserves_overrides_and_usage(client):
    """UC-28."""
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
    # The assignment result is the stored quota plus the (empty) list of acknowledged conflicts.
    assigned = response.json()
    assert assigned.pop('warnings') == []
    assert current.json() == assigned
    usage = client.get(f'/v1/platform/tenants/{tenant}/usage', headers=operator)
    assert usage.status_code == 200, usage.text
    products = next(item for item in usage.json()['dimensions'] if item['type'] == 'stored_products')
    assert products['used'] == 1 and products['limit'] == 7
    assert client.get(f'/v1/platform/tenants/{tenant}/usage', headers=headers).status_code == 401
    assert client.get(f'/v1/platform/tenants/{tenant}/quotas', headers=headers).status_code == 401
    assert client.post(f'/v1/platform/tenants/{tenant}/quotas', json={'overrides': {'stored_products': -1}}, headers=operator).status_code == 422
    assert client.get('/v1/products', headers=headers).json()['total'] == 1


def test_platform_plan_edit_updates_assigned_base_limits_and_audit(client):
    tenant, tenant_headers = provision(client)
    operator = {'Accept': 'application/json', 'Authorization': f'Bearer {get_settings().platform_admin_token}'}
    plan = next(p for p in client.get('/v1/platform/plans', headers=operator).json() if p['code'] == 'basic')
    assigned = client.post(f'/v1/platform/tenants/{tenant}/plan', json={'plan_id': plan['id']}, headers=operator)
    assert assigned.status_code == 200, assigned.text
    changed = {**plan, 'name': 'Basic verified', 'limits': {**plan['limits'], 'stored_products': plan['limits']['stored_products'] + 1}}
    try:
        assert client.put(f"/v1/platform/plans/{plan['id']}", json=changed, headers=tenant_headers).status_code == 401
        assert client.put(f"/v1/platform/plans/{plan['id']}", json={**changed, 'limits': {'stored_products': 2}}, headers=operator).status_code == 422
        response = client.put(f"/v1/platform/plans/{plan['id']}", json=changed, headers=operator)
        assert response.status_code == 200, response.text
        assert response.json()['name'] == 'Basic verified'
        quota = client.get(f'/v1/platform/tenants/{tenant}/quotas', headers=operator).json()
        assert quota['limits']['stored_products'] == changed['limits']['stored_products']
        with SessionLocal() as db, db.begin():
            set_local_tenant(db, UUID(tenant))
            assert db.scalar(select(AuditLog.id).where(AuditLog.tenant_id == UUID(tenant), AuditLog.action_type == 'plan.updated'))
    finally:
        restored = client.put(f"/v1/platform/plans/{plan['id']}", json={
            'name': plan['name'], 'limits': plan['limits'], 'is_active': plan['is_active'],
        }, headers=operator)
        assert restored.status_code == 200, restored.text


def test_operator_issued_recovery_is_single_use_and_invalidates_old_access(client):
    """UC-03."""
    tag = uuid4().hex
    email = f"recover-{tag}@example.org"
    initial_password = f"Old-{tag}!"
    created = client.post('/v1/tenants', json={'name': f'Recovery {tag}', 'admin_email': email},
                          headers={'Idempotency-Key': tag})
    assert created.status_code == 201, created.text
    tenant = created.json()['id']
    activated = client.post('/v1/auth/setup-password', json={
        'setup_token': created.json()['setup_token'], 'password': initial_password,
    })
    assert activated.status_code == 200, activated.text
    old_auth = {'Authorization': f"Bearer {activated.json()['access_token']}"}
    operator = {'Authorization': f'Bearer {get_settings().platform_admin_token}'}
    assert client.post(f'/v1/platform/tenants/{tenant}/recovery', json={'email': email}, headers=old_auth).status_code == 401
    assert client.post(f'/v1/platform/tenants/{tenant}/recovery', json={'email': 'missing@example.org'}, headers=operator).status_code == 404
    first = client.post(f'/v1/platform/tenants/{tenant}/recovery', json={'email': email}, headers=operator)
    assert first.status_code == 200, first.text
    second = client.post(f'/v1/platform/tenants/{tenant}/recovery', json={'email': email}, headers=operator)
    assert second.status_code == 200, second.text
    assert first.json()['recovery_token'] != second.json()['recovery_token']
    assert client.post('/v1/auth/recover-password', json={
        'recovery_token': first.json()['recovery_token'], 'password': 'New-Password-123',
    }).status_code == 401
    assert client.post('/v1/auth/recover-password', json={
        'recovery_token': second.json()['recovery_token'], 'password': 'New-Password-123',
        'email': 'other@example.org',
    }).status_code == 401
    changed = client.post('/v1/auth/recover-password', json={
        'recovery_token': second.json()['recovery_token'], 'password': 'New-Password-123', 'email': email,
    })
    assert changed.status_code == 200, changed.text
    assert changed.json() == {'status': 'completed'}
    assert client.post('/v1/auth/recover-password', json={
        'recovery_token': second.json()['recovery_token'], 'password': 'Again-Password-123',
    }).status_code == 401
    assert client.get('/v1/tenant/users', headers=old_auth).status_code == 401
    assert client.post('/v1/auth/login', json={'email': email, 'password': initial_password}).status_code == 401
    signed_in = client.post('/v1/auth/login', json={'email': email, 'password': 'New-Password-123'})
    assert signed_in.status_code == 200, signed_in.text
    assert client.get('/v1/tenant/users', headers={'Authorization': f"Bearer {signed_in.json()['access_token']}"}).status_code == 200
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        actions = list(db.scalars(select(AuditLog.action_type).where(AuditLog.tenant_id == UUID(tenant))))
        assert 'account_recovery_issued' in actions and 'account_recovery' in actions


def test_catalog_sync_and_event_batch_retain_item_outcomes_and_replay(client):
    """NR-F-05 / NR-F-06 / NR-NF-05 / BRULE-05 / UC-06 / UC-10 / UC-11."""
    tenant, headers = provision(client)
    _, foreign = provision(client)
    product = {'external_id': 'movie', 'title': 'Movie'}
    sync_request = {'request_id': 'sync-once', 'products': [product, product]}
    synced = client.post('/v1/products:bulk-upsert', json=sync_request, headers=headers)
    assert synced.status_code == 200, synced.text
    sync = synced.json()
    assert (sync['created_count'], sync['rejected_count']) == (1, 1)
    assert [o['status'] for o in sync['outcomes']] == ['created', 'rejected']
    assert client.post('/v1/products:bulk-upsert', json=sync_request, headers=headers).json() == sync
    assert client.post('/v1/products:bulk-upsert', json={**sync_request, 'products': [{**product, 'title': 'Changed'}]}, headers=headers).status_code == 409
    assert client.get(f"/v1/catalog-syncs/{sync['sync_id']}", headers=headers).json()['outcomes'] == sync['outcomes']
    assert client.get(f"/v1/catalog-syncs/{sync['sync_id']}", headers=foreign).status_code == 404
    assert any(item['sync_id'] == sync['sync_id'] for item in client.get('/v1/catalog-syncs', headers=headers).json())
    events = {'request_id': 'events-once', 'events': [
        {'event_id': 'good', 'event_type': 'view', 'user_id': 'shopper', 'external_product_id': 'movie'},
        {'event_id': 'bad', 'event_type': 'view', 'external_product_id': 'unknown'},
        {'event_id': 'good', 'event_type': 'view', 'user_id': 'shopper', 'external_product_id': 'movie'},
    ]}
    submitted = client.post('/v1/events/batches', json=events, headers=headers)
    assert submitted.status_code == 200, submitted.text
    batch = submitted.json()
    assert (batch['accepted_count'], batch['duplicate_count'], batch['rejected_count']) == (1, 1, 1)
    assert [o['status'] for o in batch['outcomes']] == ['accepted', 'rejected', 'duplicate']
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        assert db.scalar(select(Customer.id).where(Customer.tenant_id == UUID(tenant), Customer.external_id == 'shopper'))
    assert client.post('/v1/events/batches', json=events, headers=headers).json() == batch
    assert client.post('/v1/events', json={'event_id': 'blank-customer', 'event_type': 'view', 'user_id': ' '}, headers=headers).status_code == 422
    assert client.post('/v1/events/batches', json={**events, 'events': events['events'][:1]}, headers=headers).status_code == 409
    assert client.get(f"/v1/events/batches/{batch['id']}", headers=foreign).status_code == 404
    assert client.get(f"/v1/events/batches/{batch['id']}", headers=headers).json()['outcomes'] == batch['outcomes']
    assert client.get('/v1/products', headers=headers).json()['total'] == 1
    assert client.get('/v1/usage', headers=headers).json()['dimensions'][0]['used'] >= 0
    assert client.post('/v1/events/batches', json={'events': [{'event_id': f'e-{i}', 'event_type': 'view'} for i in range(1001)]}, headers=headers).status_code in (413, 422)


def test_concurrency_and_minute_limits_reject_excess_without_double_metering(client, monkeypatch):
    """ER-NF-07."""
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
        pending = pool.submit(client.post, '/v1/recommendations', json={'request_id': 'slow', 'user_id': 'shopper'}, headers=headers)
        try:
            assert entered.wait(5)
            blocked = client.post('/v1/recommendations', json={'user_id': 'shopper'}, headers=headers)
            assert blocked.status_code == 429, blocked.text
            assert blocked.json()['error']['details']['limit_name'] == 'concurrent_recommendation_requests'
        finally:
            release.set()
        assert pending.result().status_code == 200
    assert client.post('/v1/recommendations', json={'request_id': 'slow', 'user_id': 'shopper'}, headers=headers).status_code == 200
    rate = client.post('/v1/recommendations', json={'user_id': 'shopper'}, headers=headers)
    assert rate.status_code == 429
    assert rate.json()['error']['details']['limit_name'] == 'requests_per_minute'
    assert rate.headers['retry-after'] == '60'


def test_xr_f_06_retained_versions_limit_counts_every_non_archived_version(client):
    """D-11: active_model_versions bounds retained versions; archiving frees room."""
    tenant, headers = provision(client)
    limits(client, tenant, active_model_versions=2, training_jobs=10)
    first = client.post('/v1/model-versions', json={'version_tag': 'r1', 'model_type': 'development_placeholder'}, headers=headers)
    second = client.post('/v1/model-versions', json={'version_tag': 'r2', 'model_type': 'development_placeholder'}, headers=headers)
    assert first.status_code == second.status_code == 200
    third = client.post('/v1/model-versions', json={'version_tag': 'r3', 'model_type': 'development_placeholder'}, headers=headers)
    assert third.status_code == 429
    assert third.json()['error']['details']['limit_name'] == 'active_model_versions'
    refused_job = client.post('/v1/training-jobs', json={'configuration': {'mode': 'placeholder'}}, headers=headers)
    assert refused_job.status_code == 429
    assert client.post(f"/v1/model-versions/{first.json()['id']}:archive", headers=headers).status_code == 200
    assert client.post('/v1/model-versions', json={'version_tag': 'r3', 'model_type': 'development_placeholder'}, headers=headers).status_code == 200
    usage = {d['type']: d for d in client.get('/v1/usage', headers=headers).json()['dimensions']}
    assert usage['active_model_versions']['used'] == 2


def test_xr_f_06_plans_have_no_unenforced_limits(client):
    """D-11: Pro allows one concurrent training job (BRULE-06) and no plan lists queued_messages."""
    plans = {p['code']: p['limits'] for p in client.get('/v1/plans').json()['items']}
    assert all('queued_messages' not in limits for limits in plans.values())
    assert plans['pro']['concurrent_training_jobs'] == 1
