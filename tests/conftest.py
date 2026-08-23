"""Shared fixtures."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# Settings reads .env, which a developer machine may have customised. Pin the
# values the tests depend on before any import pulls Settings in.
os.environ.setdefault("ENVIRONMENT", "ci")
os.environ.setdefault("LOG_FORMAT", "plain")


@pytest.fixture(scope="session")
def settings():
    from graphrec.common.config import Settings

    return Settings(environment="ci")


@pytest.fixture
def app(settings):
    from apps.control_api.main import create_app

    return create_app(settings)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    # raise_server_exceptions=False so the unhandled-exception handler runs and
    # is observable, rather than the exception propagating into the test.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# --------------------------------------------------------------- database


def _owner_url() -> str:
    return os.environ.get(
        "GRAPHREC_OWNER_DATABASE_URL",
        "postgresql+psycopg://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec",
    )


@pytest.fixture(scope="session")
def owner_engine():
    """A connection as the migration owner, or an honest skip.

    A developer without a database gets a skip. CI does not: it sets
    `GRAPHREC_REQUIRE_DB=1`, which turns the skip into a failure. A required
    merge gate that quietly passes because it found nothing to run is worse than
    no gate, because it reports green.
    """
    import sqlalchemy as sa

    engine = sa.create_engine(_owner_url(), poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    except Exception as exc:
        if os.environ.get("GRAPHREC_REQUIRE_DB") == "1":
            pytest.fail(f"GRAPHREC_REQUIRE_DB=1 but the database is unreachable: {exc}")
        pytest.skip(f"no database at {_owner_url().rsplit('@', 1)[-1]}: {exc}")
    yield engine
    engine.dispose()


# ------------------------------------------------------------------ counters


@pytest.fixture(scope="session")
def counter_cache(settings):
    """A synchronous handle on the Redis the app under test counts into.

    Session-scoped because connecting once per test would cost more than the
    sweep it exists for. A machine without Redis yields `None`: the counters are
    a cache, everything that reads them repairs from the ledger on a miss, and a
    suite that could not run without one would be testing the environment.
    """
    import redis

    client = redis.Redis.from_url(str(settings.redis_url))
    try:
        client.ping()
    except Exception:
        client.close()
        yield None
        return
    yield client
    client.close()


@pytest.fixture(autouse=True)
def _sweep_counters(counter_cache) -> Iterator[None]:
    """Usage counters do not survive a test, because the ledger under them does
    not either.

    Every fixture that empties `usage_events` returns the tenant to the start of
    their month in the database — and leaves the Redis mirror of that month
    saying what it said before. The mirror is authoritative on a hit
    (`counter_ops.current` only recomputes on a *miss*), so the next test asks
    for a training run and is told its quota is exhausted by usage no table
    records. That is not a flaw in the counter: high-and-stale is the direction
    metering deliberately errs in. It is a flaw in a teardown that wiped one of
    the two places a period's total lives.

    Scanned rather than flushed. `usage:` is the whole prefix metering owns, and
    a suite that called `FLUSHDB` on a developer's Redis would take their
    sessions and their queues with it.
    """
    yield
    if counter_cache is None:
        return
    keys = list(counter_cache.scan_iter(match="usage:*", count=500))
    if keys:
        counter_cache.delete(*keys)
