"""The retry policy, written once for both transports.

Retrying asks two questions and needs both answered yes. Is the failure
transient — `GraphRecError.is_transient`, which is the server's own verdict
rather than a status-code table maintained here. And is the call idempotent —
`Spec.idempotent`, which is true only when the caller supplied the key the route
deduplicates on. A retry that changed the key would not be a retry; it would be
a second submission, which is exactly the failure this SDK refuses to generate
identifiers in order to avoid.

The budget is a deadline, not an attempt count. `timeout` bounds the whole call
including sleeps, so a recommendation on a hot path with a 200 ms budget does
not spend two seconds backing off behind the caller's back. Attempts stop when
the next delay would not fit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import random

    from .errors import GraphRecError

#: Full jitter, base 250 ms, doubling, capped at 8 s.
BASE_DELAY = 0.25
MAX_DELAY = 8.0


def backoff(attempt: int, rng: random.Random) -> float:
    # `2.0`, not `2`: `int ** int` is typed as `Any` because of the
    # negative-exponent overload, and an `Any` here would quietly widen the
    # return type of the only arithmetic in the retry policy.
    return rng.random() * min(MAX_DELAY, BASE_DELAY * 2.0**attempt)


def delay_for(attempt: int, error: GraphRecError, rng: random.Random) -> float:
    """`Retry-After` when the server named one; otherwise jittered backoff."""
    if error.retry_after_seconds is not None:
        return float(error.retry_after_seconds)
    return backoff(attempt, rng)


def will_retry(
    *,
    attempt: int,
    idempotent: bool,
    max_retries: int,
    error: GraphRecError,
    delay: float,
    remaining: float,
) -> bool:
    if not idempotent:
        return False
    if attempt >= max_retries:
        return False
    if not error.is_transient:
        return False
    return delay < remaining
