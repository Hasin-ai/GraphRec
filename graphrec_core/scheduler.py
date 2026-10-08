"""Background controller for XR-F-02/03 (retraining policies) and XR-F-08 (capacity).

Runs as its own Compose service so it keeps ticking while the training worker
is busy. Each tick discovers candidate tenants through SECURITY DEFINER
functions that return only tenant ids, then does all work inside that
tenant's row-level-security context. A Postgres advisory lock keeps a single
active scheduler; extra replicas wait as hot standbys.
"""
from __future__ import annotations

import logging
import signal
import threading
import time

from sqlalchemy import text

from graphrec_core.capacity import evaluate_capacity
from graphrec_core.database.session import SessionLocal, engine
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.retraining.service import RetrainingService
from graphrec_core.settings import get_settings

logger = logging.getLogger("graphrec.scheduler")
SCHEDULER_LOCK = 714629382


def _tenants(function: str) -> list:
    with SessionLocal() as db:
        rows = list(db.scalars(text(f"SELECT * FROM public.{function}()")))
        db.commit()
    return rows


def run_retraining_tick() -> int:
    triggered = 0
    for tenant_id in _tenants("retraining_policy_tenants"):
        try:
            with SessionLocal() as db:
                set_local_tenant(db, tenant_id)
                if RetrainingService(db).evaluate(tenant_id).trigger:
                    triggered += 1
        except Exception:
            logger.exception("Retraining evaluation failed for tenant %s", tenant_id)
    return triggered


def run_capacity_tick() -> int:
    changes = 0
    for tenant_id in _tenants("capacity_controller_tenants"):
        try:
            with SessionLocal() as db:
                set_local_tenant(db, tenant_id)
                decision = evaluate_capacity(db, tenant_id)
                changes += int(bool(decision and decision.reason))
        except Exception:
            logger.exception("Capacity evaluation failed for tenant %s", tenant_id)
    return changes


STOP = threading.Event()


def _install_signal_handlers() -> None:
    def stop(signum, _frame):  # noqa: ANN001
        logger.info("Received signal %s: stopping after the current tick", signum)
        STOP.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main() -> None:
    from graphrec_core.observability import configure_logging
    configure_logging(get_settings().effective_log_format, get_settings().log_level)
    _install_signal_handlers()
    tick = get_settings().scheduler_tick_seconds
    with engine.connect() as guard:
        while not guard.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": SCHEDULER_LOCK}):
            guard.commit()
            logger.info("Another scheduler is active; standing by")
            if STOP.wait(tick):
                return
        guard.commit()
        logger.info("Scheduler active (tick %ss)", tick)
        while not STOP.is_set():
            started = time.monotonic()
            try:
                guard.execute(text("SELECT 1"))
                guard.commit()
                run_capacity_tick()
                run_retraining_tick()
            except Exception:
                logger.exception("Scheduler tick failed")
            STOP.wait(max(1.0, tick - (time.monotonic() - started)))
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
