"""Rate limits for the five configured classes (§24 Security).

The five `*_RATE_LIMIT` settings have existed since Phase 1 and nothing read
them, which is the same failure as the `DEMO_*` settings: a limit in
`.env.example` that no request is ever counted against reads like a control.

**Fixed window, and the boundary burst is accepted deliberately.** A caller who
spends their whole allowance in the last second of one window and again in the
first second of the next gets 2x the limit across that boundary. A sliding
window fixes it and costs a sorted set per caller with a trim on every request.
For eight sign-ins a minute, the boundary case is two people getting sixteen
attempts across two seconds — which is not the attack these limits exist to
slow. The classes with volume (`usage`, `subscription`) are console reads, not
data-plane calls; ingestion and recommendations are bounded by quota, which is
metered exactly.

**Fail open, and this is the load-bearing decision.** Redis is not on the
critical path of anything else in the control plane by design, and a limiter
that refused traffic when its counter store was unreachable would turn a cache
restart into a total outage — including for `/login`, so nobody could get in to
fix it. The failure is logged at warning and, because it is a security control
silently ceasing to apply, `graphrec_rate_limit_unavailable_total` is exported
for the alert to hang from rather than left to the logs.

**Keyed on the caller, never on the route alone.** A per-route counter is a
denial-of-service primitive: one caller exhausts it and everybody is refused.
Pre-authentication classes key on the client address; the rest key on the
tenant, which is the identity the limit is actually about.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from graphrec.common.errors import LimitError
from graphrec.common.logging import get_logger
from graphrec.observability.metrics import RATE_LIMIT_UNAVAILABLE, RATE_LIMITED

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

#: Prefix for every key this module writes. One namespace, so a stuck limit can
#: be cleared with a single `SCAN`/`DEL` pass and the runbook can say so.
PREFIX = "graphrec:ratelimit"


@dataclass(frozen=True, slots=True)
class Limit:
    """One class's allowance. Named, because the 429 says which limit was hit."""

    name: str
    limit: int
    window_seconds: int


class RateLimiter:
    """Counts requests per (class, caller, window) in Redis.

    Constructed once per process and handed the client the application already
    holds, rather than opening its own: two pools to the same Redis is two
    things to configure and one of them will be missed.
    """

    def __init__(self, redis: Redis | None) -> None:
        self._redis = redis

    async def check(self, limit: Limit, caller: str) -> None:
        """Count one request, and raise `LimitError` if it is over.

        Counted *before* the work, which is the ordering the console's copy
        promises: a refused call must not have done anything. It also means a
        request that fails for another reason still consumed its allowance,
        which is correct — a caller retrying a 422 in a loop is exactly what
        these limits are for.
        """
        if limit.limit <= 0:
            return
        if self._redis is None:
            return

        window = int(time.time()) // limit.window_seconds
        key = f"{PREFIX}:{limit.name}:{caller}:{window}"
        try:
            pipeline = self._redis.pipeline()
            pipeline.incr(key)
            # Set on every request rather than only on the first. `INCR` on a
            # key with no TTL is how a limiter leaks: the expire that was meant
            # to follow the first increment is lost to any error between the
            # two, and the counter then never resets for that caller.
            pipeline.expire(key, limit.window_seconds)
            count, _ = await pipeline.execute()
        except Exception:
            RATE_LIMIT_UNAVAILABLE.labels(limit=limit.name).inc()
            logger.warning("rate_limit_unavailable", extra={"limit": limit.name})
            return

        if int(count) > limit.limit:
            RATE_LIMITED.labels(limit=limit.name).inc()
            retry_after = limit.window_seconds - int(time.time()) % limit.window_seconds
            logger.info("rate_limited", extra={"limit": limit.name, "retry_after": retry_after})
            raise LimitError(
                "rate_limited",
                retry_after_seconds=retry_after,
                copy_args={"retry_after_seconds": retry_after},
            )
