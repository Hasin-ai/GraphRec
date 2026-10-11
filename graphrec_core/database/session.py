from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from graphrec_core.settings import get_settings

_settings = get_settings()

# Every connection runs in UTC so timestamps read back from PostgreSQL serialize
# identically to the ones the API produced in memory (replays must be byte-equal,
# whatever the server's default TimeZone). A statement timeout bounds runaway
# queries on the request path.
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_timeout=_settings.db_pool_timeout_seconds,
    connect_args={
        "connect_timeout": _settings.db_connect_timeout_seconds,
        "options": f"-c timezone=UTC -c statement_timeout={_settings.db_statement_timeout_ms}",
    },
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
