"""Engines and sessions.

Two engines, because there are two database roles and the difference between
them is the isolation boundary:

* the **application** engine connects as `graphrec_app` and is what serves tenant
  traffic. Every statement it issues is subject to row-level security.
* the **platform** engine connects as `graphrec_platform`, which is granted the
  handful of tables `/admin/*` renders and nothing else.

Neither is the migration owner. Nothing in the request path ever connects as a
role that owns a table, because an owner is exempt from its own policies unless
they are `FORCE`d — and relying on `FORCE` alone leaves one mistake between a
deployment and a silent cross-tenant read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from graphrec.common.config import Settings

#: The GUC the row-level-security policies resolve. Kept here as the single
#: definition; the migration writes the same string into every policy.
TENANT_GUC = "app.tenant_id"


def create_app_engine(settings: Settings) -> AsyncEngine:
    """The engine that serves tenant traffic."""
    return _engine(settings, settings.database_url)


def create_platform_engine(settings: Settings) -> AsyncEngine:
    """The engine that serves `/v1/platform/*`."""
    return _engine(settings, settings.platform_database_url)


def _engine(settings: Settings, url: str) -> AsyncEngine:
    # `postgresql+psycopg` is natively async under create_async_engine; there is
    # no separate async driver name to substitute.
    engine = create_async_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        # A pooled connection outlives the request that used it. Recycling bounds
        # how long a connection carrying stale session state can survive, and
        # pre-ping turns a server restart into a reconnect rather than a 500.
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_pre_ping=True,
        echo=False,
        connect_args={
            # A runaway query holds a connection and, under RLS, a tenant
            # context. Bounding it server-side means a slow query fails rather
            # than exhausting the pool for every other tenant.
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
        },
    )
    _forbid_leaked_tenant_context(engine)
    return engine


def _forbid_leaked_tenant_context(engine: AsyncEngine) -> None:
    """Reset the tenant GUC whenever a connection returns to the pool.

    `SET LOCAL` is already transaction-scoped, so in correct code this is a
    no-op. It exists for the incorrect case: a `SET` issued without `LOCAL`, or a
    transaction that ended in a way that left the value behind, would otherwise
    hand the next request a connection pre-bound to somebody else's tenant. That
    failure is silent, and it returns data rather than an error.
    """

    @event.listens_for(engine.sync_engine, "reset")
    def _reset(dbapi_connection, connection_record, reset_state) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SELECT set_config('{TENANT_GUC}', '', false)")
        finally:
            cursor.close()


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )
