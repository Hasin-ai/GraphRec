from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class RegistrationRateLimiter:
    """Single-process limiter for the one-process local Compose slice."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, source: str) -> int | None:
        now = monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            attempts = self._attempts[source]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return max(1, int(self.window_seconds - (now - attempts[0])) + 1)
            attempts.append(now)
            return None

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()
