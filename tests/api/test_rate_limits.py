"""The five configured limit classes, and that each one is actually applied.

§24 Security asks for "rate limits on all five configured classes". Until
Phase 16 the five settings existed, the `rate_limited` copy existed, the 429
mapping existed, and nothing counted a request — which is the most expensive
shape a missing control can take, because everything around it reads as
evidence that it is there.

Two kinds of test here, and the second is the one that would have caught it:

* behaviour — the limiter refuses past the allowance, resets on the window,
  keys on the caller, and lets traffic through when Redis is gone;
* wiring — every one of the five classes is attached to at least one route, and
  every attached class has settings under the name it was declared with. A
  limiter with impeccable behaviour and no callers passes every test above.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest

from apps.control_api import deps
from graphrec.common.errors import LimitError
from graphrec.http.rate_limit import Limit, RateLimiter

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

#: The five §24 classes, spelled the way `Settings` spells them.
CLASSES = ("login", "registration", "api_key", "usage", "subscription")


class _FakeRedis:
    """Enough Redis to count. Not a mock of the client — a working counter.

    A `MagicMock` here would return a `MagicMock` from `execute()`, which is
    greater than every integer under comparison and would make the limiter look
    like it refused everything.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, str, int]] = []

    def incr(self, key: str) -> None:
        self._ops.append(("incr", key, 0))

    def expire(self, key: str, seconds: int) -> None:
        self._ops.append(("expire", key, seconds))

    async def execute(self) -> list[int]:
        results = []
        for op, key, seconds in self._ops:
            if op == "incr":
                self._redis.counts[key] = self._redis.counts.get(key, 0) + 1
                results.append(self._redis.counts[key])
            else:
                self._redis.expiries[key] = seconds
                results.append(1)
        return results


class _DeadRedis:
    def pipeline(self):
        raise OSError("could not reach redis at 10.10.0.1:6379")


LIMIT = Limit(name="login", limit=3, window_seconds=60)


async def test_it_allows_up_to_the_limit() -> None:
    limiter = RateLimiter(_FakeRedis())
    for _ in range(LIMIT.limit):
        await limiter.check(LIMIT, "1.2.3.4")


async def test_it_refuses_the_one_past_the_limit() -> None:
    limiter = RateLimiter(_FakeRedis())
    for _ in range(LIMIT.limit):
        await limiter.check(LIMIT, "1.2.3.4")

    with pytest.raises(LimitError) as raised:
        await limiter.check(LIMIT, "1.2.3.4")

    assert raised.value.status_code == 429
    assert raised.value.code == "rate_limited"
    # The copy names the number, so the console can render it. A `Retry-After`
    # of `None` would render as the word "None" in a sentence a customer reads.
    assert raised.value.retry_after_seconds is not None
    assert 0 < raised.value.retry_after_seconds <= LIMIT.window_seconds
    assert str(raised.value.retry_after_seconds) in raised.value.reason()


async def test_two_callers_do_not_share_an_allowance() -> None:
    """The property that separates a rate limit from a denial-of-service tool."""
    limiter = RateLimiter(_FakeRedis())
    for _ in range(LIMIT.limit):
        await limiter.check(LIMIT, "1.2.3.4")

    await limiter.check(LIMIT, "5.6.7.8")


async def test_two_classes_do_not_share_an_allowance() -> None:
    limiter = RateLimiter(_FakeRedis())
    for _ in range(LIMIT.limit):
        await limiter.check(LIMIT, "1.2.3.4")

    await limiter.check(Limit(name="usage", limit=3, window_seconds=60), "1.2.3.4")


async def test_the_window_moves_on() -> None:
    """Asserted through the key, because the alternative is sleeping a minute."""
    redis = _FakeRedis()
    limiter = RateLimiter(redis)
    await limiter.check(LIMIT, "1.2.3.4")

    windows = {key.rsplit(":", 1)[1] for key in redis.counts}
    assert windows == {str(int(time.time()) // LIMIT.window_seconds)}


async def test_every_key_carries_an_expiry() -> None:
    """`INCR` without `EXPIRE` is how a limiter becomes permanent.

    Checked on every request rather than only the first, so an error between the
    two commands cannot leave a counter that never resets — which presents as
    one caller locked out forever with nothing in the logs.
    """
    redis = _FakeRedis()
    limiter = RateLimiter(redis)
    await limiter.check(LIMIT, "1.2.3.4")
    await limiter.check(LIMIT, "1.2.3.4")

    assert set(redis.expiries.values()) == {LIMIT.window_seconds}
    assert set(redis.expiries) == set(redis.counts)


async def test_an_unreachable_redis_lets_traffic_through(caplog) -> None:
    """Fail open, loudly. See the module docstring in `rate_limit.py`.

    The alternative locks everybody out of `/login` when a cache restarts,
    including whoever would have gone in to fix it.
    """
    limiter = RateLimiter(_DeadRedis())
    with caplog.at_level("WARNING"):
        for _ in range(LIMIT.limit * 3):
            await limiter.check(LIMIT, "1.2.3.4")

    assert any("rate_limit_unavailable" in record.message for record in caplog.records)


async def test_a_limit_of_zero_is_off_not_closed() -> None:
    """`0` reads as "no limit configured", which is how it is spelled in
    `.env.example`. Treating it as "refuse everything" would make an unset
    setting an outage."""
    limiter = RateLimiter(_FakeRedis())
    for _ in range(100):
        await limiter.check(Limit(name="login", limit=0, window_seconds=60), "1.2.3.4")


# ------------------------------------------------------------------- wiring


@pytest.mark.parametrize("name", CLASSES)
def test_every_class_has_the_two_settings_it_is_read_by(name: str, settings) -> None:
    assert getattr(settings, f"{name}_rate_limit") > 0
    assert getattr(settings, f"{name}_rate_window_seconds") > 0


@pytest.mark.parametrize("name", CLASSES)
def test_every_class_is_attached_to_at_least_one_route(name: str, app) -> None:
    """The test that would have caught the gap this file exists to close.

    Walks the real route table and reads each route's dependant tree, so a class
    that is declared, configured, documented and never referenced fails here.
    """
    attached = [route.path for route in _routes(app.routes) if _applies(route, name)]
    assert attached, f"the {name!r} limit is configured but no route depends on it"


def _routes(routes: Iterable[object]) -> Iterator[Any]:
    """Every leaf route, through the nesting FastAPI 0.141 introduced.

    `app.routes` used to be flat. It now holds an `_IncludedRouter` per
    `include_router` call, which keeps its children on `original_router` and
    exposes neither `path` nor `routes`. A walker that only knows about `routes`
    finds nothing and every assertion below it passes on an empty list — which is
    how a wiring test comes to certify wiring that is not there.
    """
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _routes(included.routes)
        elif children := getattr(route, "routes", None):
            yield from _routes(children)
        else:
            yield route


def _applies(route: Any, name: str) -> bool:
    dependant = getattr(route, "dependant", None)
    return any(
        _limits(dependency.call) == name for dependency in getattr(dependant, "dependencies", [])
    )


def _limits(call: object) -> str | None:
    """Which class a dependency closure counts against.

    Read off the closure rather than off a registry, because a registry is a
    second place to remember to update — and the thing under test is precisely
    whether somebody remembered.
    """
    closure = getattr(call, "__closure__", None) or ()
    for cell in closure:
        contents = cell.cell_contents
        if isinstance(contents, str) and contents in CLASSES:
            return contents
    return None


def test_the_two_factories_are_the_only_way_a_limit_is_applied() -> None:
    """A floor for the test above: if the factories were renamed, `_limits`
    would return `None` everywhere and every route would look unlimited."""
    dependency = deps.rate_limit("login")
    assert _limits(dependency) == "login"
    assert _limits(deps.tenant_rate_limit("usage")) == "usage"
