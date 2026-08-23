"""The training worker process.

Claims only `training` jobs. Separate from `job_worker` for the reason that
module's docstring gives, and separate as a *process* rather than a thread
because torch will happily saturate every core it is given and an ingestion
handler waiting behind it would be waiting for hours.

One of these per deployment, in practice. Nothing here enforces that — the
partial unique index on `training_jobs` limits a tenant to one active run and
`SKIP LOCKED` makes a second process safe rather than harmful — but ASM-03's
platform-wide serialisation is currently a matter of running one, and Phase 9's
report says so plainly.

Draining on a signal matters more here than anywhere else in the system. A
training run that is killed at epoch 18 of 20 has done real work; letting it
reach the next checkpoint costs one epoch and saves eighteen.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from apps.training_worker.registry import build_registry
from graphrec.common.config import get_settings
from graphrec.common.logging import configure_logging, get_logger
from graphrec.db.engine import create_sessionmaker, create_worker_engine
from graphrec.jobs.worker import Worker

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    engine = create_worker_engine(settings)
    worker = Worker(
        name="training_worker",
        sessionmaker=create_sessionmaker(engine),
        registry=build_registry(),
        settings=settings,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)

    try:
        await worker.run()
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
