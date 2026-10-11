"""Graceful shutdown: the scheduler stops after its current tick on SIGTERM."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent


def _database_up() -> bool:
    try:
        from graphrec_core.database.session import engine
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _database_up(), reason="database not reachable")
def test_scheduler_exits_cleanly_on_sigterm():
    process = subprocess.Popen([sys.executable, "-m", "graphrec_core.scheduler"], cwd=ROOT,
                               env={**os.environ, "SCHEDULER_TICK_SECONDS": "1", "PYTHONPATH": str(ROOT)},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    process.send_signal(signal.SIGTERM)
    assert process.wait(15) == 0
