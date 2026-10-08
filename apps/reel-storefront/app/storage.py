"""Durable shared state for Reel storefront (Redis-backed with in-memory fallback).

Supports multi-worker uvicorn and container restarts:
* Last lists for shelf before/after diffs (TTL 24h)
* Impression event IDs linked to request IDs for click attribution (TTL 7d)
* Anonymous session events
* Telemetry feedback health counters
* Sliding window / bucket rate limiting
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SharedState:
    def __init__(self, redis_url: Optional[str] = None) -> None:
        self.redis_url = redis_url
        self._redis = None
        self._lock = threading.Lock()
        # In-memory fallbacks when Redis is not configured or unavailable
        self._local_lists: Dict[Tuple[str, str], List[str]] = {}
        self._local_impressions: Dict[str, str] = {}
        self._local_session_events: Dict[str, List[dict]] = {}
        self._local_feedback: Dict[str, Dict[str, int]] = {
            "impression": {"success": 0, "failure": 0},
            "click": {"success": 0, "failure": 0},
            "conversion": {"success": 0, "failure": 0},
        }
        self._local_rate_limits: Dict[str, List[float]] = {}

        if redis_url:
            try:
                import redis
                self._redis = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=1.5, socket_connect_timeout=1.5)
                self._redis.ping()
                logger.info("SharedState connected to Redis at %s", redis_url)
            except Exception as exc:
                logger.warning("SharedState Redis connection failed (%s); using in-memory store", exc)
                self._redis = None

    @property
    def is_redis(self) -> bool:
        return self._redis is not None

    def ping(self) -> bool:
        if self._redis:
            try:
                return bool(self._redis.ping())
            except Exception:
                return False
        return True

    def swap_last_list(self, shopper: str, shelf: str, ids: List[str], ttl: int = 86400) -> Optional[List[str]]:
        key = f"reel:last_list:{shopper}:{shelf}"
        if self._redis:
            try:
                pipe = self._redis.pipeline()
                pipe.get(key)
                pipe.set(key, json.dumps(ids), ex=ttl)
                res = pipe.execute()
                prev_raw = res[0]
                return json.loads(prev_raw) if prev_raw else None
            except Exception as exc:
                logger.warning("Redis swap_last_list failed: %s", exc)
        with self._lock:
            pair = (shopper, shelf)
            prev = self._local_lists.get(pair)
            self._local_lists[pair] = list(ids)
            return prev

    def set_impression(self, request_id: str, impression_id: str, ttl: int = 604800) -> None:
        key = f"reel:impression:{request_id}"
        if self._redis:
            try:
                self._redis.set(key, impression_id, ex=ttl)
                return
            except Exception as exc:
                logger.warning("Redis set_impression failed: %s", exc)
        with self._lock:
            self._local_impressions[request_id] = impression_id

    def get_impression(self, request_id: str) -> Optional[str]:
        key = f"reel:impression:{request_id}"
        if self._redis:
            try:
                val = self._redis.get(key)
                if val:
                    return str(val)
            except Exception as exc:
                logger.warning("Redis get_impression failed: %s", exc)
        with self._lock:
            return self._local_impressions.get(request_id)

    def record_session_event(self, session_id: str, event_data: dict, ttl: int = 2592000) -> None:
        key = f"reel:session_events:{session_id}"
        payload = json.dumps(event_data)
        if self._redis:
            try:
                pipe = self._redis.pipeline()
                pipe.rpush(key, payload)
                pipe.expire(key, ttl)
                pipe.execute()
                return
            except Exception as exc:
                logger.warning("Redis record_session_event failed: %s", exc)
        with self._lock:
            self._local_session_events.setdefault(session_id, []).append(event_data)

    def get_session_events(self, session_id: str) -> List[dict]:
        key = f"reel:session_events:{session_id}"
        if self._redis:
            try:
                raw_list = self._redis.lrange(key, 0, -1)
                return [json.loads(item) for item in raw_list]
            except Exception as exc:
                logger.warning("Redis get_session_events failed: %s", exc)
        with self._lock:
            return list(self._local_session_events.get(session_id, []))

    def record_feedback(self, kind: str, success: bool) -> None:
        field = "success" if success else "failure"
        key = f"reel:feedback_metrics:{kind}"
        if self._redis:
            try:
                self._redis.hincrby(key, field, 1)
                return
            except Exception as exc:
                logger.warning("Redis record_feedback failed: %s", exc)
        with self._lock:
            if kind in self._local_feedback:
                self._local_feedback[kind][field] += 1

    def get_feedback_health(self) -> Dict[str, Dict[str, int]]:
        out = {}
        for kind in ("impression", "click", "conversion"):
            key = f"reel:feedback_metrics:{kind}"
            if self._redis:
                try:
                    data = self._redis.hgetall(key)
                    out[kind] = {
                        "success": int(data.get("success", 0)),
                        "failure": int(data.get("failure", 0)),
                    }
                    continue
                except Exception:
                    pass
            with self._lock:
                out[kind] = dict(self._local_feedback.get(kind, {"success": 0, "failure": 0}))
        return out

    def check_rate_limit(self, identifier: str, limit: int, window_seconds: int = 60) -> Tuple[bool, int]:
        """Sliding window rate limit. Returns (allowed, retry_after_seconds)."""
        now = time.time()
        key = f"reel:ratelimit:{identifier}"
        if self._redis:
            try:
                clear_before = now - window_seconds
                pipe = self._redis.pipeline()
                pipe.zremrangebyscore(key, "-inf", clear_before)
                pipe.zcard(key)
                pipe.zadd(key, {str(now): now})
                pipe.expire(key, window_seconds + 5)
                res = pipe.execute()
                current_count = res[1]
                if current_count >= limit:
                    # Over limit: find oldest timestamp in window
                    oldest = self._redis.zrange(key, 0, 0, withscores=True)
                    retry_after = int(window_seconds - (now - oldest[0][1])) + 1 if oldest else 1
                    return False, max(1, retry_after)
                return True, 0
            except Exception as exc:
                logger.warning("Redis check_rate_limit failed: %s", exc)
        with self._lock:
            timestamps = self._local_rate_limits.setdefault(identifier, [])
            cutoff = now - window_seconds
            self._local_rate_limits[identifier] = [t for t in timestamps if t > cutoff]
            if len(self._local_rate_limits[identifier]) >= limit:
                oldest = self._local_rate_limits[identifier][0]
                retry_after = int(window_seconds - (now - oldest)) + 1
                return False, max(1, retry_after)
            self._local_rate_limits[identifier].append(now)
            return True, 0

    def close(self) -> None:
        if self._redis:
            try:
                self._redis.close()
            except Exception:
                pass
