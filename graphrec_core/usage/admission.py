"""D16: recommendation admission control (rate limit, monthly quota, concurrency slots).

State lives in Redis so every API process and replica shares one view, and each
check is a single atomic Lua call: no application lock and no read-then-write in
Python, so concurrent requests are never serialized behind each other.

* Requests per minute: exact sliding-window log in a sorted set
  ``gr:rl:{tenant}:recs`` (score = admission time in ms, Redis ``TIME``).
* Monthly recommendation quota: counter ``gr:q:{tenant}:recs:{YYYYMM}``,
  seeded once from the Postgres usage ledger, check-and-increment in Lua and
  refunded when the request does not get served.
* Concurrency: leased semaphore ``gr:slots:{tenant}`` (member = lease id,
  score = lease expiry in ms). Expired leases are reclaimed on every acquire,
  so a crashed request cannot hold a slot past ``SLOT_LEASE_SECONDS``. A full
  semaphore is retried until ``SLOT_WAIT_MS`` runs out, then 429.

Redis errors or timeouts (``REDIS_TIMEOUT_MS``) never fail a request: the check
falls back to a per-process limiter with the same limits (ER-F-09 still holds
per process), the error is logged and counted, and status endpoints report the
limiter as degraded until Redis answers again.

Circuit breaker: the first failure opens the circuit, after which requests skip
Redis entirely (no connect or DNS wait on the request path) and a background
thread probes Redis every ``PROBE_INTERVAL_SECONDS``; the first successful
probe closes the circuit. A stopped Redis container can make even name
resolution take seconds, which the socket timeout does not bound.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from graphrec_core.errors import ApiError

log = logging.getLogger("graphrec.admission")

RATE_WINDOW_MS = 60_000
PROBE_INTERVAL_SECONDS = 1.0

_RATE_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local member = ARGV[3]
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local used = redis.call('ZCARD', key)
local allowed = 0
if used < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, window + 1000)
  used = used + 1
  allowed = 1
end
local reset = window
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if oldest[2] then reset = tonumber(oldest[2]) + window - now end
return {allowed, limit - used, reset}
"""

_SLOT_ACQUIRE_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local member = ARGV[3]
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) < limit then
  redis.call('ZADD', key, now + ttl, member)
  redis.call('PEXPIRE', key, ttl + 1000)
  return 1
end
return 0
"""

_QUOTA_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local quantity = tonumber(ARGV[2])
local current = redis.call('GET', key)
if not current then return {-1, 0} end
current = tonumber(current)
if current + quantity > limit then return {0, current} end
return {1, redis.call('INCRBY', key, quantity)}
"""


@dataclass
class LimiterHealth:
    backend: str = "redis"
    fail_open_total: int = 0
    last_error_at: datetime | None = None
    last_error: str | None = None
    _last_log: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def count_fail_open(self) -> None:
        with self._lock:
            self.fail_open_total += 1

    def record_failure(self, operation: str, exc: Exception) -> None:
        with self._lock:
            self.last_error_at = datetime.now(timezone.utc)
            self.last_error = f"{operation}: {type(exc).__name__}"
            should_log = time.monotonic() - self._last_log > 10
            if should_log:
                self._last_log = time.monotonic()
        if should_log:
            log.error("admission control: Redis unavailable during %s (%s); failing open to the "
                      "per-process limiter", operation, type(exc).__name__)


@dataclass
class Lease:
    tenant_id: UUID
    lease_id: str
    local: bool


@dataclass
class RateResult:
    limit: int
    remaining: int
    reset_seconds: int

    def headers(self) -> dict[str, str]:
        return {"X-RateLimit-Limit": str(self.limit), "X-RateLimit-Remaining": str(max(0, self.remaining)),
                "X-RateLimit-Reset": str(max(0, self.reset_seconds))}


class _LocalFallback:
    """Same limits, enforced inside this process only (used while Redis is down)."""

    def __init__(self) -> None:
        self._lock = threading.Condition()
        self._rate: dict[UUID, deque[float]] = defaultdict(deque)
        self._slots: dict[UUID, int] = defaultdict(int)
        self._quota: dict[tuple[UUID, str], int] = {}

    def rate(self, tenant_id: UUID, limit: int) -> tuple[bool, int, int]:
        now = time.monotonic()
        with self._lock:
            window = self._rate[tenant_id]
            while window and window[0] <= now - RATE_WINDOW_MS / 1000:
                window.popleft()
            allowed = len(window) < limit
            if allowed:
                window.append(now)
            reset = int(window[0] + RATE_WINDOW_MS / 1000 - now) + 1 if window else RATE_WINDOW_MS // 1000
            return allowed, limit - len(window), reset

    def acquire(self, tenant_id: UUID, limit: int, wait_seconds: float) -> bool:
        deadline = time.monotonic() + wait_seconds
        with self._lock:
            while self._slots[tenant_id] >= limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._lock.wait(remaining)
            self._slots[tenant_id] += 1
            return True

    def release(self, tenant_id: UUID) -> None:
        with self._lock:
            self._slots[tenant_id] = max(0, self._slots[tenant_id] - 1)
            self._lock.notify_all()

    def quota(self, tenant_id: UUID, period: str, limit: int, quantity: int, seed: int) -> tuple[bool, int]:
        with self._lock:
            key = (tenant_id, period)
            current = max(self._quota.get(key, 0), seed)
            if current + quantity > limit:
                return False, current
            self._quota[key] = current + quantity
            return True, current + quantity

    def refund(self, tenant_id: UUID, period: str, quantity: int) -> None:
        with self._lock:
            key = (tenant_id, period)
            if key in self._quota:
                self._quota[key] = max(0, self._quota[key] - quantity)

    def clear(self) -> None:
        with self._lock:
            self._rate.clear(); self._slots.clear(); self._quota.clear()
            self._lock.notify_all()


class AdmissionController:
    def __init__(self, redis_url: str | None, *, timeout_ms: int = 30, slot_wait_ms: int = 100,
                 slot_lease_seconds: int = 30, client=None) -> None:
        self.slot_wait_ms = slot_wait_ms
        self.slot_lease_ms = slot_lease_seconds * 1000
        self.health = LimiterHealth(backend="redis" if (redis_url or client is not None) else "local")
        self.local = _LocalFallback()
        self._client = client
        if self._client is None and redis_url:
            import redis
            timeout = timeout_ms / 1000
            self._client = redis.Redis.from_url(redis_url, socket_timeout=timeout, socket_connect_timeout=timeout,
                                                retry_on_timeout=False, health_check_interval=0)
        self._circuit_open = False
        self._probe_lock = threading.Lock()
        self._probe_thread: threading.Thread | None = None
        if self._client is not None:
            self._rate_script = self._client.register_script(_RATE_LUA)
            self._acquire_script = self._client.register_script(_SLOT_ACQUIRE_LUA)
            self._quota_script = self._client.register_script(_QUOTA_LUA)

    # -- circuit breaker --------------------------------------------------
    def _redis_available(self) -> bool:
        return self._client is not None and not self._circuit_open

    def _fail(self, operation: str, exc: Exception) -> None:
        self.health.record_failure(operation, exc)
        self._circuit_open = True
        with self._probe_lock:
            if self._probe_thread is None or not self._probe_thread.is_alive():
                self._probe_thread = threading.Thread(target=self._probe, name="admission-redis-probe", daemon=True)
                self._probe_thread.start()

    def _probe(self) -> None:
        while self._circuit_open:
            time.sleep(PROBE_INTERVAL_SECONDS)
            try:
                self._client.ping()
            except Exception:  # noqa: BLE001 - still down
                continue
            self._circuit_open = False
            log.warning("admission control: Redis reachable again; shared limits resumed")

    # -- status -----------------------------------------------------------
    def status(self) -> dict:
        state = "ok"
        if self._client is None:
            state = "disabled"
        elif self._circuit_open:
            state = "degraded"
        else:
            try:
                self._client.ping()
            except Exception as exc:  # noqa: BLE001 - any Redis failure is "degraded"
                self._fail("ping", exc)
                state = "degraded"
        return {"backend": self.health.backend, "status": state, "fail_open_total": self.health.fail_open_total,
                "last_error_at": self.health.last_error_at.isoformat() if self.health.last_error_at else None}

    def _redis_errors(self):
        import redis
        return (redis.RedisError, OSError)

    # -- concurrency ------------------------------------------------------
    def acquire_slot(self, tenant_id: UUID, limit: int) -> Lease:
        lease_id = uuid4().hex
        deadline = time.monotonic() + self.slot_wait_ms / 1000
        if self._redis_available():
            try:
                while True:
                    if int(self._acquire_script(keys=[f"gr:slots:{tenant_id}"],
                                                args=[limit, self.slot_lease_ms, lease_id])):
                        return Lease(tenant_id, lease_id, local=False)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise _slots_full(limit)
                    time.sleep(min(0.01, remaining))
            except self._redis_errors() as exc:
                self._fail("slot acquire", exc)
        if self._client is not None:
            self.health.count_fail_open()   # admitted without the shared store
        if self.local.acquire(tenant_id, limit, max(0.0, deadline - time.monotonic())):
            return Lease(tenant_id, lease_id, local=True)
        raise _slots_full(limit)

    def release(self, lease: Lease) -> None:
        if lease.local:
            self.local.release(lease.tenant_id)
            return
        if not self._redis_available():
            return  # the lease expires on its own after SLOT_LEASE_SECONDS
        try:
            self._client.zrem(f"gr:slots:{lease.tenant_id}", lease.lease_id)
        except self._redis_errors() as exc:  # the lease expires on its own
            self._fail("slot release", exc)

    # -- requests per minute ---------------------------------------------
    def check_rate(self, tenant_id: UUID, limit: int) -> RateResult:
        if self._redis_available():
            try:
                allowed, remaining, reset_ms = (int(v) for v in self._rate_script(
                    keys=[f"gr:rl:{tenant_id}:recs"], args=[limit, RATE_WINDOW_MS, uuid4().hex]))
                result = RateResult(limit, remaining, -(-reset_ms // 1000))
                if not allowed:
                    raise _rate_limited(limit, result)
                return result
            except self._redis_errors() as exc:
                self._fail("rate check", exc)
        allowed, remaining, reset = self.local.rate(tenant_id, limit)
        result = RateResult(limit, remaining, reset)
        if not allowed:
            raise _rate_limited(limit, result)
        return result

    # -- monthly quota ----------------------------------------------------
    def consume_quota(self, tenant_id: UUID, dimension: str, limit: int, period_start: datetime,
                      period_end: datetime, seed: Callable[[], int], quantity: int = 1) -> None:
        period = period_start.strftime("%Y%m")
        if self._redis_available():
            key = f"gr:q:{tenant_id}:{dimension}:{period}"
            try:
                status, used = (int(v) for v in self._quota_script(keys=[key], args=[limit, quantity]))
                if status == -1:
                    self._client.set(key, int(seed()), nx=True, exat=int(period_end.timestamp()) + 86_400)
                    status, used = (int(v) for v in self._quota_script(keys=[key], args=[limit, quantity]))
                if status == 1:
                    return
                raise _quota_exhausted(dimension, limit, used, quantity, period_end)
            except self._redis_errors() as exc:
                self._fail("quota check", exc)
        allowed, used = self.local.quota(tenant_id, period, limit, quantity, int(seed()))
        if not allowed:
            raise _quota_exhausted(dimension, limit, used, quantity, period_end)

    def refund_quota(self, tenant_id: UUID, dimension: str, period_start: datetime, quantity: int = 1) -> None:
        period = period_start.strftime("%Y%m")
        if self._redis_available():
            try:
                self._client.decrby(f"gr:q:{tenant_id}:{dimension}:{period}", quantity)
                return
            except self._redis_errors() as exc:
                self._fail("quota refund", exc)
        self.local.refund(tenant_id, period, quantity)


def _slots_full(limit: int) -> ApiError:
    return ApiError(429, "quota_exceeded", "Concurrent recommendation capacity is in use.", retryable=True,
                    retry_after_seconds=1, details={"limit_name": "concurrent_recommendation_requests", "limit": limit})


def _rate_limited(limit: int, result: RateResult) -> ApiError:
    error = ApiError(429, "quota_exceeded", "The recommendation request rate limit has been reached.",
                     retryable=True, retry_after_seconds=max(1, result.reset_seconds),
                     details={"limit_name": "requests_per_minute", "limit": limit, "used": limit})
    error.headers = result.headers()
    return error


def _quota_exhausted(dimension: str, limit: int, used: int, quantity: int, period_end: datetime) -> ApiError:
    return ApiError(429, "quota_exceeded", f"The {dimension} limit has been reached.",
                    details={"limit_name": dimension, "limit": limit, "used": int(used),
                             "requested": quantity, "reset_at": period_end.isoformat()})


_controller: AdmissionController | None = None
_controller_lock = threading.Lock()


def get_admission() -> AdmissionController:
    global _controller
    if _controller is None:
        with _controller_lock:
            if _controller is None:
                from graphrec_core.settings import get_settings
                s = get_settings()
                _controller = AdmissionController(s.redis_url, timeout_ms=s.redis_timeout_ms,
                                                  slot_wait_ms=s.slot_wait_ms, slot_lease_seconds=s.slot_lease_seconds)
    return _controller


def set_admission(controller: AdmissionController | None) -> None:
    """Swap the process controller (tests and fault injection)."""
    global _controller
    with _controller_lock:
        _controller = controller
