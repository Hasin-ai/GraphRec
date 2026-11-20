"""A-15: replayed responses must not change timestamp offsets with the server timezone."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from graphrec_core.database.session import SessionLocal

pytestmark = pytest.mark.integration


def test_every_connection_reads_timestamps_in_utc():
    with SessionLocal() as db:
        assert db.scalar(text("SHOW TimeZone")) == "UTC"
        assert db.scalar(text("SELECT EXTRACT(TIMEZONE FROM now())")) == 0


def test_statement_timeout_is_bounded():
    with SessionLocal() as db:
        assert db.scalar(text("SHOW statement_timeout")) not in ("0", "")
