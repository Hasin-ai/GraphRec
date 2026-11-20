"""D16: recommendation admission end to end (Compose Postgres + Redis)."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from tests.integration.test_srs_acceptance import limits, provision

pytestmark = pytest.mark.integration

BIG = dict(concurrent_recommendation_requests=50, requests_per_minute=1000)


def tenant_with_product(client, **overrides):
    tenant, headers = provision(client)
    assert client.put('/v1/products/movie', json={'external_id': 'movie', 'title': 'Movie'}, headers=headers).status_code == 200
    limits(client, tenant, **{**BIG, **overrides})
    return tenant, headers


def recommend(client, headers, user='shopper'):
    return client.post('/v1/recommendations', json={'user_id': user}, headers=headers)


def slow_serve(monkeypatch, seconds):
    from apps.api.routes import recommendations
    original = recommendations._serve

    def slow(*args):
        time.sleep(seconds)
        return original(*args)
    monkeypatch.setattr(recommendations, '_serve', slow)


def test_concurrent_recommendations_are_not_serialized(client, monkeypatch):
    _, headers = tenant_with_product(client)
    slow_serve(monkeypatch, 0.4)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = [r.status_code for r in pool.map(lambda i: recommend(client, headers, f'u{i}'), range(5))]
    elapsed = time.monotonic() - started
    assert statuses == [200] * 5
    assert elapsed < 1.2, f"5 parallel 0.4 s requests took {elapsed:.2f} s (serialized would be >= 2 s)"


def test_rate_limit_is_exact_under_concurrency_with_headers(client):
    _, headers = tenant_with_product(client, requests_per_minute=10)
    with ThreadPoolExecutor(max_workers=15) as pool:
        responses = list(pool.map(lambda i: recommend(client, headers, f'u{i}'), range(15)))
    codes = [r.status_code for r in responses]
    assert codes.count(200) == 10 and codes.count(429) == 5
    denied = next(r for r in responses if r.status_code == 429)
    assert denied.json()['error']['details']['limit_name'] == 'requests_per_minute'
    assert denied.json()['error']['message'] == 'The recommendation request rate limit has been reached.'
    assert int(denied.headers['retry-after']) >= 1
    assert denied.headers['x-ratelimit-limit'] == '10' and denied.headers['x-ratelimit-remaining'] == '0'
    served = next(r for r in responses if r.status_code == 200)
    assert served.headers['x-ratelimit-limit'] == '10' and int(served.headers['x-ratelimit-remaining']) < 10


def test_request_waits_for_a_slot_that_frees_within_the_budget(client, monkeypatch):
    _, headers = tenant_with_product(client, concurrent_recommendation_requests=1)
    slow_serve(monkeypatch, 0.05)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(recommend, client, headers, 'a')
        time.sleep(0.01)
        second = pool.submit(recommend, client, headers, 'b')
        assert first.result().status_code == 200
        assert second.result().status_code == 200, second.result().text


def test_request_gets_429_when_no_slot_frees_within_the_budget(client, monkeypatch):
    _, headers = tenant_with_product(client, concurrent_recommendation_requests=1)
    slow_serve(monkeypatch, 0.6)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(recommend, client, headers, 'a')
        time.sleep(0.1)
        started = time.monotonic()
        blocked = recommend(client, headers, 'b')
        waited = time.monotonic() - started
        assert first.result().status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()['error']['details']['limit_name'] == 'concurrent_recommendation_requests'
    assert blocked.json()['error']['message'] == 'Concurrent recommendation capacity is in use.'
    assert 0.09 <= waited < 0.45


def test_slot_and_quota_are_released_when_serving_fails(client, monkeypatch):
    tenant, headers = tenant_with_product(client, concurrent_recommendation_requests=1)
    from apps.api.routes import recommendations

    def boom(*args):
        raise RuntimeError("serving crashed")
    original = recommendations._serve
    monkeypatch.setattr(recommendations, '_serve', boom)
    with TestClient(app, raise_server_exceptions=False) as failing:
        assert recommend(failing, headers).status_code == 500
    monkeypatch.setattr(recommendations, '_serve', original)
    started = time.monotonic()
    assert recommend(client, headers).status_code == 200
    assert time.monotonic() - started < 0.09        # no wait: the failed request released its slot


def test_one_tenant_never_consumes_another_tenants_limits(client, monkeypatch):
    _, a = tenant_with_product(client, concurrent_recommendation_requests=1, requests_per_minute=2)
    _, b = tenant_with_product(client, concurrent_recommendation_requests=1, requests_per_minute=2)
    assert [recommend(client, a).status_code for _ in range(3)] == [200, 200, 429]   # A's rate exhausted
    assert recommend(client, b).status_code == 200                                    # B untouched
    _, c = tenant_with_product(client, concurrent_recommendation_requests=1)
    slow_serve(monkeypatch, 0.5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        held = pool.submit(recommend, client, c, 'x')                                 # C's only slot is busy
        time.sleep(0.1)
        started = time.monotonic()
        assert recommend(client, b).status_code == 200                                # B's slot is free
        assert time.monotonic() - started < 0.5 + 0.3
        assert held.result().status_code == 200


def test_redis_outage_fails_open_shows_degraded_and_limits_return(client):
    from graphrec_core.usage import admission as admission_module
    healthy = admission_module.get_admission()
    _, headers = tenant_with_product(client, requests_per_minute=1)
    admission_module.set_admission(admission_module.AdmissionController('redis://127.0.0.1:1/0', timeout_ms=30))
    try:
        assert recommend(client, headers).status_code == 200
        status = client.get('/v1/deployment', headers=headers).json()['rate_limiter']
        assert status['status'] == 'degraded' and status['fail_open_total'] >= 1
    finally:
        admission_module.set_admission(healthy)
    assert client.get('/v1/deployment', headers=headers).json()['rate_limiter']['status'] == 'ok'
    assert recommend(client, headers).status_code == 200      # first call in the shared window
    assert recommend(client, headers).status_code == 429      # shared limit applies again
