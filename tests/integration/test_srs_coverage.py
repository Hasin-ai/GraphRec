"""SRS requirements that no other test verified on its own (see docs/GAP_ANALYSIS.md).

Each test names the requirement it checks in its docstring. None of them runs the
training worker: jobs are created and observed, never claimed.
"""
from __future__ import annotations

import ast
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest

from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.settings import get_settings
from tests.integration.test_xr_features import operator, provision, seed_trainable

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
PLATFORM = {'Accept': 'application/json'}


def platform_headers():
    return {**PLATFORM, 'Authorization': f'Bearer {get_settings().platform_admin_token}'}


def api_key(client, admin, scopes):
    created = client.post('/v1/api-keys', json={'name': f'k-{uuid4().hex[:8]}', 'scopes': scopes}, headers=admin)
    assert created.status_code == 201, created.text
    return {'Accept': 'application/json', 'Authorization': f"ApiKey {created.json()['secret']}"}


def placeholder_versions(client, headers, count):
    versions = []
    for _ in range(count):
        job = client.post('/v1/training-jobs', json={'configuration': {'mode': 'placeholder'}}, headers=headers)
        assert job.status_code == 200, job.text
        versions.append(job.json()['model_version_id'])
    return versions


def statuses(client, headers):
    return {v['id']: v['status'] for v in client.get('/v1/model-versions', headers=headers).json()['items']}


# ---- NR-F-08 / UC-13 ---------------------------------------------------------
def test_nr_f_08_uc_13_job_stage_and_progress_are_reported_from_the_worker(client):
    """NR-F-08 / UC-13: the job detail shows the stage and progress the worker records,
    and progress never moves backwards."""
    from graphrec_core.dgsr.worker import progress

    tenant, admin = provision(client)
    operator(client, tenant, training_jobs=5)
    seed_trainable(client, admin)
    created = client.post('/v1/training-jobs', json={'configuration': {'mode': 'train', 'epochs': 1}}, headers=admin)
    assert created.status_code == 200, created.text
    job_id = created.json()['id']
    try:
        queued = client.get(f'/v1/training-jobs/{job_id}', headers=admin).json()
        assert queued['status'] == 'queued' and queued['progress'] == 0
        progress(UUID(tenant), UUID(job_id), 'training', 40)
        running = client.get(f'/v1/training-jobs/{job_id}', headers=admin).json()
        assert (running['stage'], running['progress']) == ('training', 40)
        progress(UUID(tenant), UUID(job_id), 'evaluating_test', 30)
        later = client.get(f'/v1/training-jobs/{job_id}', headers=admin).json()
        assert (later['stage'], later['progress']) == ('evaluating_test', 40)
        listed = next(j for j in client.get('/v1/training-jobs', headers=admin).json()['items'] if j['id'] == job_id)
        assert (listed['stage'], listed['progress']) == ('evaluating_test', 40)
        _, other = provision(client)
        assert client.get(f'/v1/training-jobs/{job_id}', headers=other).status_code == 404
    finally:
        client.post(f'/v1/training-jobs/{job_id}:cancel', headers=admin)


# ---- NR-F-13 -----------------------------------------------------------------
def test_nr_f_13_session_recommendations_endpoint(client):
    """NR-F-13: POST /v1/recommendations/session serves an anonymous session, needs
    recommendations:read, and rejects a request with no usable session."""
    tenant, admin = provision(client)
    seed_trainable(client, admin)
    store = api_key(client, admin, ['recommendations:read', 'events:write', 'catalog:read'])
    body = {'context': {'session_id': 's-1', 'recent_product_ids': ['p1']}, 'top_n': 3}
    served = client.post('/v1/recommendations/session', json=body, headers=store)
    assert served.status_code == 200, served.text
    result = served.json()
    assert result['request_id'] and 1 <= len(result['items']) <= 3
    assert result['strategy'] == 'popular_fallback' and result['model_version_id'] is None
    assert all(item['external_product_id'].startswith('p') for item in result['items'])
    reader = api_key(client, admin, ['catalog:read'])
    denied = client.post('/v1/recommendations/session', json=body, headers=reader)
    assert denied.status_code == 403 and denied.json()['error']['code'] == 'insufficient_scope'
    assert client.post('/v1/recommendations/session', json={'context': {'surface': 'cart'}}, headers=store).status_code == 422


# ---- XR-F-01 -----------------------------------------------------------------
class _RecordingArtifact:
    """Stands in for a DGSR artifact and records what the route encodes."""

    def __init__(self, items):
        self.item_ids = list(items)
        self.encoded, self.excluded = None, None

    def user_index(self, user_id):
        return None

    def item_index(self, item):
        return self.item_ids.index(item) if item in self.item_ids else None

    def encode_history(self, events, user=None):
        self.encoded = [self.item_ids[e.item] for e in events]

        class Encoded:
            query = np.ones(2)
            strategy = 'personalized'
        return Encoded()

    def score(self, query, excluded_rows):
        self.excluded = sorted(self.item_ids[i] for i in excluded_rows)
        scores = np.arange(len(self.item_ids), dtype=float)
        scores[list(excluded_rows)] = -np.inf
        return scores

    def top_k(self, scores, k):
        order = [i for i in np.argsort(-scores, kind='stable') if np.isfinite(scores[i])]
        return [(self.item_ids[i], float(scores[i])) for i in order[:k]]


def test_xr_f_01_stored_history_and_session_context_are_encoded_together(client, monkeypatch):
    """XR-F-01: the shopper's stored events (oldest first) and the session's recent
    products together form the encoded history, and every seen item is excluded."""
    from apps.api.routes import recommendations
    from graphrec_core.schemas.recommendations import RecommendationRequest

    tenant, admin = provision(client)
    seed_trainable(client, admin)
    artifact = _RecordingArtifact([f'p{i}' for i in range(9)])
    monkeypatch.setattr('graphrec_core.dgsr.serving.load_artifact', lambda directory: artifact)

    def qdrant_unreachable():
        raise ConnectionError('no qdrant in this test')
    monkeypatch.setattr(recommendations, 'get_qdrant_client', qdrant_unreachable)
    payload = RecommendationRequest.model_validate({'user_id': 'u0', 'top_n': 2, 'context': {'recent_product_ids': ['p7']}})
    with SessionLocal() as db:
        set_local_tenant(db, UUID(tenant))
        candidates, strategy = recommendations._dgsr_candidates(db, UUID(tenant), uuid4(), Path('.'), payload, 5)
    # seed_trainable gives u0 views of p0..p5 in time order.
    assert artifact.encoded == ['p0', 'p1', 'p2', 'p3', 'p4', 'p5', 'p7']
    assert artifact.excluded == ['p0', 'p1', 'p2', 'p3', 'p4', 'p5', 'p7']
    assert strategy == 'personalized' and candidates == ['p8', 'p6']
    session_only = RecommendationRequest.model_validate({'context': {'session_id': 's', 'recent_product_ids': ['p2']}})
    with SessionLocal() as db:
        set_local_tenant(db, UUID(tenant))
        recommendations._dgsr_candidates(db, UUID(tenant), uuid4(), Path('.'), session_only, 5)
    assert artifact.encoded == ['p2']


# ---- ER-F-07 -----------------------------------------------------------------
def test_er_f_07_rollback_accepts_only_a_retired_version_of_the_same_tenant(client):
    """ER-F-07: rollback is refused for a never-active, active, archived, unknown or
    foreign version, and succeeds for the retired previous version."""
    tenant, admin = provision(client)
    _, other = provision(client)
    operator(client, tenant, training_jobs=5, active_model_versions=10)
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=admin).status_code == 200
    first, second = placeholder_versions(client, admin, 2)
    assert client.post(f'/v1/model-versions/{first}:activate', headers=admin).status_code == 200
    never_active = client.post(f'/v1/models/{second}:rollback', headers=admin)
    assert never_active.status_code == 409 and never_active.json()['error']['code'] == 'model_not_eligible'
    assert client.post(f'/v1/models/{first}:rollback', headers=admin).status_code == 409   # already active
    assert client.post(f'/v1/model-versions/{second}:activate', headers=admin).status_code == 200
    spare = client.post('/v1/model-versions', json={'version_tag': 'spare', 'model_type': 'development_placeholder'}, headers=admin)
    assert spare.status_code == 200, spare.text
    assert client.post(f"/v1/model-versions/{spare.json()['id']}:archive", headers=admin).status_code == 200
    assert client.post(f"/v1/models/{spare.json()['id']}:rollback", headers=admin).status_code == 409
    assert client.post(f'/v1/models/{uuid4()}:rollback', headers=admin).status_code == 404
    assert client.post(f'/v1/models/{first}:rollback', headers=other).status_code == 404
    assert client.get('/v1/deployment', headers=admin).json()['active_model_version_id'] == second
    restored = client.post(f'/v1/models/{first}:rollback', headers=admin)
    assert restored.status_code == 200, restored.text
    assert statuses(client, admin)[first] == 'active' and statuses(client, admin)[second] == 'retired'


# ---- BRULE-08 ----------------------------------------------------------------
def test_brule_08_concurrent_activations_leave_exactly_one_active_version(client):
    """BRULE-08: lifecycle changes are serialized; concurrent activations demote the
    previous version and leave exactly one active version, matching the deployment."""
    tenant, admin = provision(client)
    operator(client, tenant, training_jobs=5, active_model_versions=10)
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=admin).status_code == 200
    first, second, third = placeholder_versions(client, admin, 3)
    assert client.post(f'/v1/model-versions/{first}:activate', headers=admin).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda v: client.post(f'/v1/model-versions/{v}:activate', headers=admin), [second, third]))
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    state = statuses(client, admin)
    active = [v for v, s in state.items() if s == 'active']
    assert len(active) == 1 and active[0] in (second, third)
    assert state[first] == 'retired'
    assert client.get('/v1/deployment', headers=admin).json()['active_model_version_id'] == active[0]


# ---- ER-NF-06 ----------------------------------------------------------------
def test_er_nf_06_identical_requests_get_identical_rankings(client):
    """ER-NF-06: the same request (new request ids, unchanged data) returns the same
    items in the same order, with and without reranking rules."""
    _, admin = provision(client)
    seed_trainable(client, admin)

    def ranking():
        body = {'request_id': uuid4().hex, 'user_id': 'cold-shopper', 'top_n': 6}
        response = client.post('/v1/recommendations', json=body, headers=admin)
        assert response.status_code == 200, response.text
        return [i['external_product_id'] for i in response.json()['items']]

    plain = [ranking() for _ in range(3)]
    assert len(plain[0]) == 6 and plain[0] == plain[1] == plain[2]
    rules = {'diversity_enabled': True, 'max_per_category': 1, 'freshness_enabled': True,
             'freshness_weight': 0.2, 'freshness_half_life_days': 30}
    assert client.put('/v1/recommendation-policy', json=rules, headers=admin).status_code == 200
    reranked = [ranking() for _ in range(3)]
    assert len(reranked[0]) == 6 and reranked[0] == reranked[1] == reranked[2]


# ---- UC-26 / NR-F-16 ---------------------------------------------------------
def test_uc_26_nr_f_16_service_status_measures_the_tenants_own_traffic(client):
    """UC-26 / NR-F-16: the metrics summary counts the tenant's served requests, their
    fallback rate and latency, and nothing from other tenants; the deployment reports
    that no model is active."""
    _, admin = provision(client)
    _, other = provision(client)
    seed_trainable(client, admin)
    empty = client.get('/v1/metrics/summary', headers=admin).json()
    assert empty['request_count'] == 0 and empty['error_rate'] is None and empty['p95_latency_ms'] is None
    for i in range(3):
        assert client.post('/v1/recommendations', json={'user_id': f's{i}', 'top_n': 2}, headers=admin).status_code == 200
    summary = client.get('/v1/metrics/summary', params={'window_minutes': 60}, headers=admin).json()
    assert summary['request_count'] == 3
    assert summary['error_rate'] == 0 and summary['fallback_rate'] == 1
    assert summary['p95_latency_ms'] is not None and summary['p95_latency_ms'] >= 0
    assert summary['active_model_version_id'] is None
    assert client.get('/v1/metrics/summary', headers=other).json()['request_count'] == 0
    deployment = client.get('/v1/deployment', headers=admin)
    assert deployment.status_code == 200 and deployment.json()['active_model_version_id'] is None


# ---- UC-30 -------------------------------------------------------------------
def test_uc_30_platform_status_reports_serving_capacity_across_tenants(client):
    """UC-30: the platform status reflects a tenant's newly ready deployment and is
    closed to tenant credentials."""
    tenant, admin = provision(client)
    operator(client, tenant, training_jobs=3)
    before = client.get('/v1/platform/status', headers=platform_headers())
    assert before.status_code == 200, before.text
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=admin).status_code == 200
    version, = placeholder_versions(client, admin, 1)
    assert client.post(f'/v1/model-versions/{version}:activate', headers=admin).status_code == 200
    after = client.get('/v1/platform/status', headers=platform_headers()).json()
    assert after['database'] == 'connected' and after['status'] in {'healthy', 'degraded'}
    assert isinstance(after['worker_pool'], str) and after['rate_limiter']['status']
    assert after['deployments']['available_tenants'] == before.json()['deployments']['available_tenants'] + 1
    assert after['deployments']['ready_capacity'] >= after['deployments']['available_tenants']
    assert client.get('/v1/platform/status', headers=admin).status_code == 401


# ---- BRULE-04 ----------------------------------------------------------------
def test_brule_04_external_product_ids_are_unique_per_tenant_only(client):
    """BRULE-04: a product external id identifies one product within a tenant (a repeat
    upsert updates it), while another tenant may use the same id independently."""
    _, a = provision(client)
    _, b = provision(client)
    product = {'external_id': 'shared-sku', 'title': 'First'}
    assert client.put('/v1/products/shared-sku', json=product, headers=a).status_code == 200
    assert client.put('/v1/products/shared-sku', json={**product, 'title': 'Second'}, headers=a).status_code == 200
    listed = client.get('/v1/products', headers=a).json()
    assert listed['total'] == 1 and listed['items'][0]['title'] == 'Second'
    assert client.put('/v1/products/shared-sku', json={**product, 'title': 'Other'}, headers=b).status_code == 200
    assert client.get('/v1/products/shared-sku', headers=a).json()['title'] == 'Second'
    assert client.get('/v1/products/shared-sku', headers=b).json()['title'] == 'Other'


# ---- NR-NF-04 ----------------------------------------------------------------
def test_nr_nf_04_mixed_storefront_traffic_at_the_supported_concurrency(client):
    """NR-NF-04: 8 concurrent shoppers sending the documented mix (70 % recommendations,
    20 % events, 10 % product reads) get no errors and a bounded p95. This is an
    in-process smoke check of docs/PERFORMANCE.md, not the full load test."""
    tenant, admin = provision(client)
    operator(client, tenant, concurrent_recommendation_requests=50, requests_per_minute=10_000)
    seed_trainable(client, admin)

    def call(i):
        started = time.perf_counter()
        kind = i % 10
        if kind < 7:
            response = client.post('/v1/recommendations', json={'user_id': f'u{i % 4}', 'top_n': 5}, headers=admin)
        elif kind < 9:
            response = client.post('/v1/events', json={'event_id': f'load-{i}', 'event_type': 'view',
                                   'user_id': f'u{i % 4}', 'external_product_id': f'p{i % 9}'}, headers=admin)
        else:
            response = client.get(f'/v1/products/p{i % 9}', headers=admin)
        return response.status_code, (time.perf_counter() - started) * 1000

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call, range(160)))
    failed = [code for code, _ in results if code >= 300]
    assert not failed, failed
    latencies = sorted(ms for _, ms in results)
    p95 = latencies[math.ceil(0.95 * len(latencies)) - 1]
    assert p95 < 2000, f'p95 {p95:.0f} ms'


# ---- ER-F-03 -----------------------------------------------------------------
def test_er_f_03_offline_metrics_have_the_documented_values():
    """ER-F-03: Hit@1, Hit@10, NDCG@10, MRR@10 and catalog coverage@10 computed on known
    ranks (1, 3, 11 and an unknown target) equal their definitions."""
    from graphrec_core.dgsr.evaluation import CommonExample, evaluate_popularity

    catalog = [chr(ord('a') + i) for i in range(12)]
    train = [item for rank, item in enumerate(catalog) for _ in range(12 - rank)]  # a most popular, l least
    examples = [CommonExample('u1', (('z', 1),), 'a'),     # rank 1
                CommonExample('u2', (('a', 1),), 'd'),     # a excluded: b, c, d -> rank 3
                CommonExample('u3', (('z', 1),), 'k'),     # rank 11: outside the top 10
                CommonExample('u4', (('z', 1),), 'zzz')]   # not in the catalog
    result = evaluate_popularity(train, catalog, examples)
    assert result['examples'] == 4 and result['unknown_targets'] == 1
    assert result['Hit@1'] == pytest.approx(1 / 4)
    assert result['Hit@10'] == pytest.approx(2 / 4)
    assert result['NDCG@10'] == pytest.approx((1 + 1 / math.log2(4)) / 4)
    assert result['MRR@10'] == pytest.approx((1 + 1 / 3) / 4)
    assert result['catalog_coverage@10'] == pytest.approx(11 / 12)   # a..j plus k (u2's list)


# ---- ER-NF-08 ----------------------------------------------------------------
def test_er_nf_08_core_library_does_not_depend_on_the_api_layer():
    """ER-NF-08: graphrec_core holds the domain modules and never imports the FastAPI
    application package, so the API layer can change without touching the core."""
    offenders = []
    for path in (ROOT / 'graphrec_core').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ''] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            offenders += [f'{path.relative_to(ROOT)}: {n}' for n in names if n == 'apps' or n.startswith('apps.')]
    assert not offenders, offenders
    domains = {'auth', 'api_keys', 'catalog', 'events', 'models_reg', 'registration', 'usage', 'dgsr', 'database'}
    assert domains <= {p.name for p in (ROOT / 'graphrec_core').iterdir() if p.is_dir() and any(p.glob('*.py'))}


def test_uc_25_model_status_reports_every_state_and_an_explicit_empty_state(client, monkeypatch):
    """UC-25 / NR-F-16: a new tenant has no versions and a stopped deployment; versions move
    eligible -> active -> retired; a failed activation is reported and the previous version
    stays active; another tenant sees none of it."""
    tenant, admin = provision(client)
    _, other = provision(client)
    operator(client, tenant, training_jobs=5, active_model_versions=5)
    assert client.get('/v1/model-versions', headers=admin).json() == {'items': []}
    empty = client.get('/v1/deployment', headers=admin).json()
    assert empty['status'] == 'stopped' and empty['active_model_version_id'] is None
    client.put('/v1/products/m', json={'external_id': 'm', 'title': 'M'}, headers=admin)
    first = client.post('/v1/training-jobs', json={'request_id': 'uc25-1', 'configuration': {'mode': 'placeholder'}}, headers=admin).json()['model_version_id']
    assert client.get(f'/v1/model-versions/{first}', headers=admin).json()['status'] == 'eligible'
    assert client.post(f'/v1/model-versions/{first}:activate', headers=admin).status_code == 200
    broken = client.post('/v1/model-versions', json={'version_tag': 'broken', 'model_type': 'dgsr',
                         'artifact_uri': 'file:///nonexistent/artifact'}, headers=admin).json()['id']
    failed = client.post(f'/v1/model-versions/{broken}:activate', headers=admin)
    assert failed.status_code >= 400
    deployment = client.get('/v1/deployment', headers=admin).json()
    assert deployment['active_model_version_id'] == first           # the old version keeps serving
    statuses = {v['id']: v['status'] for v in client.get('/v1/model-versions', headers=admin).json()['items']}
    assert statuses[first] == 'active' and statuses[broken] in {'eligible', 'failed'}
    monkeypatch.setattr(get_settings(), 'training_cooldown_seconds', 0)
    second = client.post('/v1/training-jobs', json={'request_id': 'uc25-2', 'configuration': {'mode': 'placeholder'}}, headers=admin)
    assert second.status_code == 200, second.text
    second_id = second.json()['model_version_id']
    assert client.post(f'/v1/model-versions/{second_id}:activate', headers=admin).status_code == 200
    statuses = {v['id']: v['status'] for v in client.get('/v1/model-versions', headers=admin).json()['items']}
    assert statuses[first] == 'retired' and statuses[second_id] == 'active'
    assert client.get('/v1/model-versions', headers=other).json() == {'items': []}
    assert client.get(f'/v1/model-versions/{first}', headers=other).status_code == 404
