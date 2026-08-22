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
