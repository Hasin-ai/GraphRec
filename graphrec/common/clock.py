"""Time.

One source of truth for "now", injectable so that cooldowns, token expiry,
credential expiry and lease expiry are testable without sleeping. Server time is
authoritative for derived state the console renders — a credential's `usable` /
`expired` state is computed here, never from the client's clock (BUILD_PROMPT
§10.9).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """UTC, always timezone-aware. A naive datetime is a bug, not a shortcut."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Test double. Advances only when told to."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._at += timedelta(seconds=seconds)


_default = SystemClock()


def utcnow() -> datetime:
    return _default.now()
