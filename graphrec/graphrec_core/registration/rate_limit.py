from __future__ import annotations

from graphrec_core.usage.admission import get_admission


class SharedRateLimiter:
    """Sliding-window limiter shared by every API process (A-01).

    Attempts are recorded in Redis through the admission controller, so the limit
    holds across uvicorn workers and replicas. If Redis is unavailable the check
    falls back to a per-process window with the same limit: authentication limits
    degrade to per-process, never to unlimited. Subjects are hashed before use.
    """

    def __init__(self, name: str, limit: int, window_seconds: int) -> None:
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds

    def check(self, subject: str) -> int | None:
        """Admit one attempt; return the seconds to wait when the limit is reached."""
        return get_admission().check_window(self.name, subject, self.limit, self.window_seconds)

    def clear(self) -> None:
        get_admission().clear_windows(self.name)


# Backwards-compatible name used by earlier modules and tests.
RegistrationRateLimiter = SharedRateLimiter
