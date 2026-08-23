"""The ingestion worker process.

Claims event batches and bulk product upserts. Training is deliberately not
here: it is globally serialised (ASM-03), it wants a differently-shaped machine,
and a GPU process blocked on CSV validation is a GPU process doing nothing.

Two of these can run side by side with no coordination between them. That is
what `FOR UPDATE … SKIP LOCKED` buys — see migration 0006.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from redis.asyncio import ConnectionPool, Redis

from apps.job_worker.registry import registry
from graphrec.common.config import get_settings
from graphrec.common.logging import configure_logging, get_logger
from graphrec.db.engine import create_sessionmaker, create_worker_engine
from graphrec.domain.metering.counters import RedisUsageCounters, ResilientUsageCounters
from graphrec.jobs.worker import Worker

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    engine = create_worker_engine(settings)
    # The same Redis the control API reads, not the process-local default.
    # `Worker` falls back to an in-memory pair so a test or a one-off run needs
    # no Redis, and a *deployed* worker taking that default would move a counter
    # nobody else can see: the ledger would stay right, `/v1/usage` would
    # under-report every asynchronously ingested batch, and a quota check would
    # keep passing on a stale number until the key expired.
    redis_pool = ConnectionPool.from_url(str(settings.redis_url))
    redis = Redis(connection_pool=redis_pool)
    worker = Worker(
        name="job_worker",
        sessionmaker=create_sessionmaker(engine),
        registry=registry,
        settings=settings,
        # Wrapped, because an unreachable cache must not stop an ingestion:
        # `counters.current` repairs from the ledger on a miss.
        counters=ResilientUsageCounters(RedisUsageCounters(redis)),
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Drain rather than abort. An in-flight job is left to finish, so a
        # deploy does not manufacture half-applied ingestions for its own
        # operators to reconcile.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)

    try:
        await worker.run()
    finally:
        await engine.dispose()
        await redis.aclose()
        # The client returns its own connection; the pool holds the rest.
        await redis_pool.disconnect()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
