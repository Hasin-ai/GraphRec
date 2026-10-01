"""API and isolation tests for XR-F-02/03 (retraining), XR-F-04 (rules),
XR-F-07 (usage trends) and XR-F-08 (serving capacity)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from graphrec_core.auth.passwords import hash_password
from graphrec_core.capacity import evaluate_capacity
from graphrec_core.database.models import (CapacityEvent, RetrainingPolicy, ServingRequest, TenantUser,
                                           TrainingJob, UsageEvent)
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.retraining.service import RetrainingService
from graphrec_core.settings import get_settings

pytestmark = pytest.mark.integration
JSON = {"Accept": "application/json"}


def provision(client):
    tag = uuid4().hex
    created = client.post('/v1/tenants', json={'name': f'XR {tag}', 'admin_email': f'{tag}@example.org'},
                          headers={**JSON, 'Idempotency-Key': tag})
    assert created.status_code == 201, created.text
    auth = client.post('/v1/auth/setup-password', json={'setup_token': created.json()['setup_token'],
                       'password': f'Test-{tag}!'}, headers=JSON)
    assert auth.status_code == 200, auth.text
    return created.json()['id'], {**JSON, 'Authorization': f"Bearer {auth.json()['access_token']}"}


def developer(client, tenant):
    email, password = f'dev-{uuid4().hex[:10]}@example.org', 'xr developer password'
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        db.add(TenantUser(id=uuid4(), tenant_id=UUID(tenant), email=email, display_name='Dev',
            credential_digest=hash_password(password), role='tenant_developer', status='active',
            created_at=datetime.now(timezone.utc)))
    login = client.post('/v1/auth/login', json={'email': email, 'password': password}, headers=JSON)
    assert login.status_code == 200, login.text
    return {**JSON, 'Authorization': f"Bearer {login.json()['access_token']}"}


def operator(client, tenant, **overrides):
    response = client.post(f'/v1/platform/tenants/{tenant}/quotas', json={'overrides': overrides},
        headers={**JSON, 'Authorization': f'Bearer {get_settings().platform_admin_token}'})
    assert response.status_code == 200, response.text


def seed_trainable(client, headers, categories=('shoes', 'hats', 'bags')):
    products = [{'external_id': f'p{i}', 'title': f'P{i}', 'category': categories[i % len(categories)]} for i in range(9)]
    assert client.post('/v1/products:bulk-upsert', json={'products': products}, headers=headers).status_code == 200
    base = datetime.now(timezone.utc) - timedelta(days=1)
    events = [{'event_id': f'e{u}-{i}', 'event_type': 'view', 'user_id': f'u{u}', 'external_product_id': f'p{(u + i) % 9}',
               'occurred_at': (base + timedelta(minutes=i)).isoformat()} for u in range(3) for i in range(6)]
    events += [{'event_id': f'pop{i}', 'event_type': 'purchase', 'user_id': 'u9', 'external_product_id': 'p0',
                'occurred_at': (base + timedelta(minutes=30 + i)).isoformat()} for i in range(5)]
    batch = client.post('/v1/events/batches', json={'events': events}, headers=headers)
    assert batch.status_code == 200 and batch.json()['rejected_count'] == 0, batch.text


# ---- XR-F-02 / XR-F-03 ---------------------------------------------------
def test_retraining_policy_permissions_validation_and_isolation(client):
    tenant, admin = provision(client)
    _, other = provision(client)
    dev = developer(client, tenant)
    assert client.get('/v1/retraining-policy', headers=admin).json()['configured'] is False
    minimum = get_settings().retraining_min_interval_minutes
    body = {'schedule_enabled': True, 'interval_minutes': minimum, 'event_trigger_enabled': True,
            'event_threshold': 5, 'epochs': 2}
    saved = client.put('/v1/retraining-policy', json=body, headers=admin)
    assert saved.status_code == 200, saved.text
    assert saved.json()['configured'] and saved.json()['next_run_at'] is not None
    assert client.get('/v1/retraining-policy', headers=dev).status_code == 200   # training:read
    assert client.put('/v1/retraining-policy', json=body, headers=dev).status_code == 403
    if minimum > 1:
        too_short = client.put('/v1/retraining-policy', json={**body, 'interval_minutes': minimum - 1}, headers=admin)
        assert too_short.status_code == 422
    assert client.put('/v1/retraining-policy', json={**body, 'epochs': 11}, headers=admin).status_code == 422
    # Tenant isolation: another tenant sees only its own (unconfigured) policy and cannot alter ours.
    assert client.get('/v1/retraining-policy', headers=other).json()['configured'] is False
    client.put('/v1/retraining-policy', json={**body, 'event_threshold': 999}, headers=other)
    assert client.get('/v1/retraining-policy', headers=admin).json()['event_threshold'] == 5


def test_schedule_fires_once_per_slot_and_not_while_training(client):
    tenant, admin = provision(client)
    operator(client, tenant, training_jobs=5)
    seed_trainable(client, admin)
    body = {'schedule_enabled': True, 'interval_minutes': get_settings().retraining_min_interval_minutes,
            'event_trigger_enabled': False, 'event_threshold': 1000, 'epochs': 1}
    assert client.put('/v1/retraining-policy', json=body, headers=admin).status_code == 200
    tid = UUID(tenant)
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tid)
        db.execute(update(RetrainingPolicy).where(RetrainingPolicy.tenant_id == tid)
                   .values(next_run_at=datetime.now(timezone.utc) - timedelta(seconds=5)))
    for _ in range(3):
        with SessionLocal() as db:
            set_local_tenant(db, tid)
            RetrainingService(db).evaluate(tid)
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tid)
        assert db.scalar(select(func.count(TrainingJob.id)).where(TrainingJob.tenant_id == tid)) == 1
    policy = client.get('/v1/retraining-policy', headers=admin).json()
    assert policy['last_trigger'] == 'schedule' and policy['last_outcome'] == 'training_requested'
    assert datetime.fromisoformat(policy['next_run_at']) > datetime.now(timezone.utc)
    assert policy['training_in_progress'] is True


def test_event_trigger_fires_exactly_once_per_condition(client):
    tenant, admin = provision(client)
    operator(client, tenant, training_jobs=5)
    seed_trainable(client, admin)
    body = {'schedule_enabled': False, 'interval_minutes': 1440, 'event_trigger_enabled': True,
            'event_threshold': 10, 'epochs': 1}
    assert client.put('/v1/retraining-policy', json=body, headers=admin).status_code == 200
    assert client.get('/v1/retraining-policy', headers=admin).json()['new_events_since_last_training'] >= 10
    tid = UUID(tenant)
    triggers = []
    for _ in range(3):
        with SessionLocal() as db:
            set_local_tenant(db, tid)
            triggers.append(RetrainingService(db).evaluate(tid).trigger)
    assert triggers == ['events', None, None]
    job = client.get('/v1/training-jobs', headers=admin).json()['items'][0]
    assert client.post(f"/v1/training-jobs/{job['id']}:cancel", headers=admin).status_code == 200
    with SessionLocal() as db:
        set_local_tenant(db, tid)
        assert RetrainingService(db).evaluate(tid).trigger is None   # counter reset by the job
    assert client.get('/v1/retraining-policy', headers=admin).json()['new_events_since_last_training'] == 0


# ---- XR-F-04 -------------------------------------------------------------
def test_recommendation_rules_change_output_respect_exclusions_and_isolation(client):
    tenant, admin = provision(client)
    _, other = provision(client)
    dev = developer(client, tenant)
    seed_trainable(client, admin, categories=('shoes', 'shoes', 'shoes', 'hats'))
    request = {'user_id': 'nobody-yet', 'top_n': 4}
    off = client.post('/v1/recommendations', json=request, headers=admin).json()
    assert off['applied_rules'] == [] and off['rules_version'] is None
    rules = {'diversity_enabled': True, 'max_per_category': 1, 'freshness_enabled': False,
             'freshness_weight': 0.2, 'freshness_half_life_days': 30}
    saved = client.put('/v1/recommendation-policy', json=rules, headers=admin)
    assert saved.status_code == 200 and saved.json()['version'] == 1
    assert client.put('/v1/recommendation-policy', json=rules, headers=admin).json()['version'] == 1
    on = client.post('/v1/recommendations', json=request, headers=admin).json()
    assert on['applied_rules'] == ['diversity'] and on['rules_version'] == 1
    cats = {f'p{i}': ('shoes', 'shoes', 'shoes', 'hats')[i % 4] for i in range(9)}
    spread = lambda r: len({cats[i['external_product_id']] for i in r['items']})
    # Only two categories exist, and the cap relaxes rather than shortening the
    # list, so the measurable effect is the head of the list: with a cap of 1
    # the first two items must come from different categories.
    head = lambda r: [cats[i['external_product_id']] for i in r['items'][:2]]
    assert len(set(head(on))) == 2 and spread(on) >= spread(off)
    excluded = client.post('/v1/recommendations', json={**request, 'exclude_product_ids': ['p0', 'p3']}, headers=admin).json()
    assert not {'p0', 'p3'} & {i['external_product_id'] for i in excluded['items']}
    assert client.put('/v1/recommendation-policy', json={**rules, 'freshness_weight': 0.4}, headers=admin).status_code == 422
    assert client.put('/v1/recommendation-policy', json={**rules, 'max_per_category': 2}, headers=admin).json()['version'] == 2
    assert client.get('/v1/recommendation-policy', headers=dev).status_code == 403
    assert client.put('/v1/recommendation-policy', json=rules, headers=dev).status_code == 403
    assert client.get('/v1/recommendation-policy', headers=other).json()['configured'] is False


# ---- XR-F-07 -------------------------------------------------------------
def test_usage_trends_match_ledger_and_are_isolated(client):
    tenant, admin = provision(client)
    _, other = provision(client)
    seed_trainable(client, admin)
    trend = client.get('/v1/usage/trends', params={'granularity': 'hour', 'types': 'accepted_events',
                       'start': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}, headers=admin)
    assert trend.status_code == 200, trend.text
    data = trend.json()
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        ledger = db.scalar(select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
            UsageEvent.tenant_id == UUID(tenant), UsageEvent.usage_type == 'accepted_events'))
    assert data['totals']['accepted_events'] == int(ledger) > 0
    assert sum(b['values']['accepted_events'] for b in data['buckets']) == int(ledger)
    assert 48 <= len(data['buckets']) <= 49
    assert client.get('/v1/usage/trends', params={'granularity': 'hour',
        'start': (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()}, headers=admin).status_code == 422
    assert client.get('/v1/usage/trends?types=bogus', headers=admin).status_code == 422
    assert client.get('/v1/usage/trends?granularity=month', headers=admin).status_code == 422
    assert client.get('/v1/usage/trends?types=accepted_events', headers=other).json()['totals']['accepted_events'] == 0


# ---- XR-F-08 -------------------------------------------------------------
def test_capacity_scales_with_load_is_observable_and_isolated(client, monkeypatch):
    tenant, admin = provision(client)
    _, other = provision(client)
    dev = developer(client, tenant)
    operator(client, tenant, training_jobs=3, maximum_inference_replicas=3, concurrent_recommendation_requests=9)
    assert client.get('/v1/deployment/scaling', headers=admin).json()['managed'] is False
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=admin).status_code == 200
    version = client.post('/v1/training-jobs', json={'configuration': {'mode': 'placeholder'}}, headers=admin).json()['model_version_id']
    assert client.post(f'/v1/model-versions/{version}:activate', headers=admin).status_code == 200
    settings = get_settings()
    monkeypatch.setattr(settings, 'capacity_target_rpm_per_replica', 10)
    monkeypatch.setattr(settings, 'capacity_scale_down_stabilization_seconds', 0)
    tid, now = UUID(tenant), datetime.now(timezone.utc)
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tid)
        for i in range(25):
            db.add(ServingRequest(id=uuid4(), tenant_id=tid, model_version_id=UUID(version), strategy='popular_fallback',
                                  outcome='served', fallback_used=True, item_count=1, latency_ms=5,
                                  occurred_at=now - timedelta(seconds=i)))
    with SessionLocal() as db:
        set_local_tenant(db, tid)
        assert evaluate_capacity(db, tid).target == 3          # 25 rpm / 10 -> 3 (clamped to plan max 3)
    status = client.get('/v1/deployment/scaling', headers=admin).json()
    assert status['managed'] and status['ready_capacity'] == 3 and status['serving_slots'] == 9
    assert status['events'][0]['reason'] == 'scale_up' and status['events'][0]['to_capacity'] == 3
    assert client.get('/v1/deployment', headers=admin).json()['ready_capacity'] == 3
    with SessionLocal() as db:
        set_local_tenant(db, tid)
        # Two hours later the burst has left every measurement window.
        assert evaluate_capacity(db, tid, now + timedelta(hours=2)).target == 1   # scale down
    assert client.get('/v1/deployment/scaling', headers=admin).json()['events'][0]['reason'] == 'scale_down'
    assert client.get('/v1/deployment/scaling', headers=dev).status_code == 403   # no deployments:read
    foreign = client.get('/v1/deployment/scaling', headers=other).json()
    assert foreign['managed'] is False and foreign['events'] == []
