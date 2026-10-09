"""Last-good recommendation lists in Redis (degradation tier, fail-open).

A served list is remembered per tenant and shopper (or session) for a short
time. When a later request comes up short - a source timed out, the catalogue
changed - the remembered list tops it up after being re-checked for
eligibility. Redis problems never fail a request: after an error the cache is
bypassed for ``BACKOFF_SECONDS`` so a dead Redis adds no latency.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from uuid import UUID

from graphrec_core.settings import get_settings

logger = logging.getLogger(__name__)

TTL_SECONDS = 600
BACKOFF_SECONDS = 30
TIMEOUT_SECONDS = 0.05
MAX_ITEMS = 100

_lock = threading.Lock()
_client = None
_disabled_until = 0.0


def _redis():
    global _client
    if time.monotonic() < _disabled_until:
        return None
    url = get_settings().redis_url
    if not url:
        return None
    with _lock:
        if _client is None:
            import redis

            _client = redis.Redis.from_url(url, socket_timeout=TIMEOUT_SECONDS,
                                           socket_connect_timeout=TIMEOUT_SECONDS)
        return _client


def _fail(exc: Exception) -> None:
    global _disabled_until
    _disabled_until = time.monotonic() + BACKOFF_SECONDS
    logger.warning("Last-good cache unavailable for %ss: %s", BACKOFF_SECONDS, exc)


def key(tenant_id: UUID, user_id: str | None, session_id: str | None) -> str | None:
    if user_id:
        return f"graphrec:lastgood:{tenant_id}:u:{user_id}"
    if session_id:
        return f"graphrec:lastgood:{tenant_id}:s:{session_id}"
    return None


def load(cache_key: str | None) -> list[str]:
    if not cache_key:
        return []
    client = _redis()
    if client is None:
        return []
    try:
        raw = client.get(cache_key)
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
        return []
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [str(v) for v in value][:MAX_ITEMS] if isinstance(value, list) else []


def store(cache_key: str | None, items: list[str]) -> None:
    if not cache_key or not items:
        return
    client = _redis()
    if client is None:
        return
    try:
        client.set(cache_key, json.dumps(items[:MAX_ITEMS]), ex=TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
