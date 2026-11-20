"""D16: Redis admission control (unit level, against the Compose Redis)."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from graphrec_core.errors import ApiError
from graphrec_core.settings import get_settings

redis = pytest.importorskip("redis")
from graphrec_core.usage.admission import AdmissionController  # noqa: E402

URL = get_settings().redis_url


def _redis_up() -> bool:
    try:
        return bool(URL) and redis.Redis.from_url(URL, socket_timeout=0.2, socket_connect_timeout=0.2).ping()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_up(), reason="Redis (REDIS_URL) is not reachable")


def controller(**kw) -> AdmissionController:
    kw.setdefault("timeout_ms", 200)
    return AdmissionController(URL, **kw)


class FlakyClient:
    """Wraps a real client; raises ConnectionError while ``down`` is set."""

    def __init__(self, real):
        self.real, self.down = real, False

    def _guard(self):
        if self.down:
            raise redis.ConnectionError("injected outage")

    def register_script(self, source):
        script = self.real.register_script(source)

        def run(*a, **kw):
            self._guard()
            return script(*a, **kw)
        return run

    def __getattr__(self, name):
        attr = getattr(self.real, name)

        def call(*a, **kw):
            self._guard()
            return attr(*a, **kw)
        return call


def test_rate_limit_is_exact_under_concurrency():
    admission, tenant = controller(), uuid4()

    def attempt(_):
        try:
            admission.check_rate(tenant, 12)
            return 200
        except ApiError as exc:
            assert exc.details["limit_name"] == "requests_per_minute"
            assert exc.headers["X-RateLimit-Remaining"] == "0" and exc.retry_after_seconds >= 1
            return 429

    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(attempt, range(20)))
    assert outcomes.count(200) == 12 and outcomes.count(429) == 8


def test_slot_wait_succeeds_when_a_slot_frees_within_the_budget():
    admission, tenant = controller(slot_wait_ms=100), uuid4()
    held = admission.acquire_slot(tenant, 1)
    threading.Timer(0.03, admission.release, args=(held,)).start()
    started = time.monotonic()
    lease = admission.acquire_slot(tenant, 1)
    assert 0.02 <= time.monotonic() - started < 0.1
    admission.release(lease)


def test_slot_wait_times_out_with_429_after_the_budget():
    admission, tenant = controller(slot_wait_ms=100), uuid4()
    held = admission.acquire_slot(tenant, 1)
    started = time.monotonic()
    with pytest.raises(ApiError) as caught:
        admission.acquire_slot(tenant, 1)
    elapsed = time.monotonic() - started
    assert caught.value.status_code == 429 and caught.value.message == "Concurrent recommendation capacity is in use."
    assert 0.09 <= elapsed < 0.3
    admission.release(held)


def test_lease_of_a_killed_request_is_reclaimed_after_the_ttl():
    admission, tenant = controller(slot_wait_ms=0, slot_lease_seconds=1), uuid4()
    admission.acquire_slot(tenant, 1)            # never released: the holder "crashed"
    with pytest.raises(ApiError):
        admission.acquire_slot(tenant, 1)
    time.sleep(1.1)
    admission.release(admission.acquire_slot(tenant, 1))


def test_tenants_never_share_slots_or_rate():
    admission, a, b = controller(slot_wait_ms=0), uuid4(), uuid4()
    held = admission.acquire_slot(a, 1)
    for _ in range(3):
        admission.check_rate(a, 3)
    with pytest.raises(ApiError):
        admission.check_rate(a, 3)
    admission.release(admission.acquire_slot(b, 1))
    assert admission.check_rate(b, 3).remaining == 2
    admission.release(held)


def test_two_replicas_share_limits():
    first, second, tenant = controller(slot_wait_ms=0), controller(slot_wait_ms=0), uuid4()
    held = first.acquire_slot(tenant, 1)
    with pytest.raises(ApiError):
        second.acquire_slot(tenant, 1)
    first.release(held)
    second.release(second.acquire_slot(tenant, 1))
    first.check_rate(tenant, 2)
    second.check_rate(tenant, 2)
    with pytest.raises(ApiError):
        first.check_rate(tenant, 2)


def test_monthly_quota_is_seeded_from_the_ledger_and_refundable():
    admission, tenant = controller(), uuid4()
    start, end = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 11, 1, tzinfo=timezone.utc)
    admission.consume_quota(tenant, "recommendation_requests", 3, start, end, seed=lambda: 2)
    with pytest.raises(ApiError) as caught:
        admission.consume_quota(tenant, "recommendation_requests", 3, start, end, seed=lambda: 0)
    assert caught.value.details["used"] == 3
    admission.refund_quota(tenant, "recommendation_requests", start)
    admission.consume_quota(tenant, "recommendation_requests", 3, start, end, seed=lambda: 0)


def test_redis_outage_fails_open_reports_degraded_and_recovers():
    flaky = FlakyClient(redis.Redis.from_url(URL))
    admission, tenant = AdmissionController(None, client=flaky, slot_wait_ms=0), uuid4()
    flaky.down = True
    lease = admission.acquire_slot(tenant, 1)         # served without Redis
    assert lease.local
    admission.check_rate(tenant, 100)
    assert admission.status()["status"] == "degraded"
    assert admission.health.fail_open_total >= 1
    admission.release(lease)
    flaky.down = False
    deadline = time.monotonic() + 3                     # background probe closes the circuit
    while admission.status()["status"] != "ok" and time.monotonic() < deadline:
        time.sleep(0.1)
    assert admission.status()["status"] == "ok"
    for _ in range(2):
        admission.check_rate(tenant, 2)                 # shared limits apply again
    with pytest.raises(ApiError):
        admission.check_rate(tenant, 2)


class SlowDownClient(FlakyClient):
    """An outage where every Redis call stalls (e.g. DNS for a stopped container)."""

    def _guard(self):
        if self.down:
            time.sleep(0.5)
            raise redis.ConnectionError("stalled")


def test_open_circuit_keeps_stalled_redis_off_the_request_path():
    stalled = SlowDownClient(redis.Redis.from_url(URL))
    admission, tenant = AdmissionController(None, client=stalled, slot_wait_ms=0), uuid4()
    stalled.down = True
    admission.release(admission.acquire_slot(tenant, 5))   # first request pays one stall and opens the circuit
    started = time.monotonic()
    for _ in range(10):
        admission.release(admission.acquire_slot(tenant, 5))
        admission.check_rate(tenant, 100)
    assert time.monotonic() - started < 0.2               # later requests never wait on Redis
    assert admission.status()["status"] == "degraded"
    stalled.down = False
    deadline = time.monotonic() + 3
    while admission.status()["status"] != "ok" and time.monotonic() < deadline:
        time.sleep(0.1)
    lease = admission.acquire_slot(tenant, 5)
    assert not lease.local                                 # shared store in use again
    admission.release(lease)


def test_unreachable_redis_answers_within_the_client_timeout():
    admission, tenant = AdmissionController("redis://127.0.0.1:1/0", timeout_ms=30, slot_wait_ms=0), uuid4()
    started = time.monotonic()
    admission.release(admission.acquire_slot(tenant, 2))
    admission.check_rate(tenant, 5)
    assert time.monotonic() - started < 0.5
    assert admission.status()["status"] == "degraded"
