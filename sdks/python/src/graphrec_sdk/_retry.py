"""Retry policy.

The SDK retries only when doing so cannot duplicate a side effect:

* **Rate limiting** (``429 rate_limit_exceeded``) and **declared-retryable
  503s** are rejected before GraphRec changes anything, so every route may
  retry them. ``Retry-After`` / ``retry_after_seconds`` is honoured.
* **Connection failures before the request was sent** (DNS, refused, pool
  timeout) are always safe.
* **Ambiguous failures** (read timeouts, dropped connections, 502/504 from a
  proxy) are retried only for idempotent routes - reads, upserts, and writes
  deduplicated by ``event_id`` or ``Idempotency-Key``.

``quota_exceeded`` and every other 4xx are never retried.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

import httpx

from ._constants import (
    DEFAULT_MAX_RETRIES,
    INITIAL_RETRY_DELAY,
    MAX_RETRY_AFTER_SECONDS,
    MAX_RETRY_DELAY,
)
from ._routes import Route
from .errors import APIStatusError

__all__ = ["RetryPolicy"]

_PRE_SEND_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = DEFAULT_MAX_RETRIES
    initial_delay: float = INITIAL_RETRY_DELAY
    max_delay: float = MAX_RETRY_DELAY
    #: A server-requested wait longer than this is surfaced as an error instead.
    max_retry_after: float = MAX_RETRY_AFTER_SECONDS
    jitter: float = 0.25

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")

    def backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter for zero-based ``attempt``."""

        base = min(self.initial_delay * (2.0**attempt), self.max_delay)
        spread = base * self.jitter
        return max(0.0, base + random.uniform(-spread, spread))

    def delay_for_status(
        self, error: APIStatusError, route: Route, attempt: int
    ) -> Optional[float]:
        """Seconds to wait before retrying ``error``, or ``None`` to give up."""

        if attempt >= self.max_retries:
            return None
        retry_after = error.retry_after_seconds
        if error.code == "quota_exceeded":
            return None
        rejected_before_processing = error.status_code == 429 or (
            error.status_code == 503 and error.retryable
        )
        gateway_failure = error.status_code in {502, 504} and route.idempotent
        if not (rejected_before_processing or gateway_failure):
            return None
        if retry_after is not None:
            if retry_after > self.max_retry_after:
                return None
            return retry_after
        return self.backoff(attempt)

    def delay_for_exception(
        self, exc: httpx.TransportError, route: Route, attempt: int
    ) -> Optional[float]:
        if attempt >= self.max_retries:
            return None
        if isinstance(exc, _PRE_SEND_ERRORS) or route.idempotent:
            return self.backoff(attempt)
        return None
