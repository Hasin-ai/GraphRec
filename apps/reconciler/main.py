"""The reconciler process — the loop around `domain.serving.reconciler.converge`.

There is exactly one decision in this file and it is not about deployments: it
is *whether this process is the one making them*. Everything else — apply,
observe, record, swap, fail — lives in the domain, where it is callable from a
test without starting a daemon.

**One leader, elected by PostgreSQL.** `pg_try_advisory_lock` on a session this
process holds open for its whole life (ADR 0028). Two reconcilers converging one
tenant would both call `apply` with different epochs and fight over the replica
count, and the loser's `up --scale` would undo the winner's. A follower does not
wait on the lock: it sleeps and tries again, so a rolling deploy has a standby
that takes over the moment the leader's connection drops, without anyone having
to observe that it died.

**Two roles, and the sweep uses the smaller one.** Enumerating the deployments
that need attention is a cross-tenant read, which the tenant role cannot do and
should not be able to. The platform role can — of `model_deployments` it holds
`SELECT (deployment_id, tenant_id, state, desired_replicas, ready_replicas,
last_transition_at)` and nothing else (migration 0012), so the sweep can learn
that a tenant has a deployment to converge and cannot learn what it is serving.
The convergence itself then runs on a tenant-bound session under RLS, exactly
like a request would.

**A tenant that raises does not stop the pass.** Failures are per tenant and are
logged with the tenant id; the loop continues to the next one. A reconciler that
died on one tenant's unreachable Docker daemon would leave every other tenant's
activation hanging until somebody noticed, which is the opposite of what a
convergence loop is for.

**Shutdown drains, it does not abort.** `SIGTERM` sets a flag; the pass in
flight finishes, the lock is released, and the engines are disposed. A pass
killed between `apply` and `_record_replicas` leaves containers running that no
row describes — recoverable, but only by the next leader, and only after the
activation timeout has burned.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import signal
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.config import get_settings
from graphrec.common.enums import TenantStatus
from graphrec.common.logging import configure_logging, get_logger, tenant_id_var
from graphrec.db.engine import create_platform_engine, create_sessionmaker, create_worker_engine
from graphrec.db.models import Job, ModelDeployment, Tenant
from graphrec.db.tenant_context import bind_tenant
from graphrec.domain.serving.deployment import DeploymentService
from graphrec.domain.serving.reconciler import (
    acquire_leadership,
    converge,
    release_leadership,
)
from graphrec.jobs.states import JobType, QueueStatus
from graphrec.observability.exposition import start_metrics_server
from graphrec.observability.metrics import (
    JOB_QUEUE_DEPTH,
    JOB_QUEUE_OLDEST_SECONDS,
    SERVING_REPLICAS,
)
from graphrec.serving_driver import build_serving_driver

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from graphrec.domain.serving.reconciler import ConvergenceResult
    from graphrec.serving_driver import ServingDriver

logger = get_logger(__name__)


class Reconciler:
    """The loop, and the two things it needs to be told: how to reach the
    database and how to reach the orchestrator.

    A class rather than a function because the signal handlers need something to
    say `stop` to, and because a test wants to run `pass_once` without ever
    entering the sleep.
    """

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        platform_sessionmaker: async_sessionmaker[AsyncSession],
        driver: ServingDriver,
        interval_seconds: float,
        activation_timeout: dt.timedelta,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._platform_sessionmaker = platform_sessionmaker
        self._driver = driver
        self._interval = interval_seconds
        self._activation_timeout = activation_timeout
        self._deployments = DeploymentService()
        self._stopping = asyncio.Event()
        self._leader = False

    def request_stop(self) -> None:
        """Finish the pass in flight, then exit. Idempotent, because a
        supervisor that sends `SIGTERM` twice is a supervisor being careful."""
        if not self._stopping.is_set():
            logger.info("reconciler_stopping")
            self._stopping.set()

    async def run(self) -> None:
        """Hold one session for the lock; open fresh ones for the work.

        The lock session issues one statement and then does nothing for the life
        of the process. That is the point — a session advisory lock is released
        when its connection goes, so the lock's lifetime *is* this session's,
        and giving the work its own sessions keeps a slow convergence from
        holding the connection the election depends on.
        """
        async with self._sessionmaker() as elector:
            try:
                while not self._stopping.is_set():
                    await self._tick(elector)
                    await self._sleep()
            finally:
                if self._leader:
                    await release_leadership(elector)
                    self._leader = False

    async def _tick(self, elector: AsyncSession) -> None:
        """Stand for election if we are not the leader; converge if we are."""
        if not self._leader:
            self._leader = await acquire_leadership(elector)
            if not self._leader:
                # Normal, and not worth a line every five seconds. A standby is
                # doing its job by being idle.
                logger.debug("reconciler_standby")
                return
            logger.info("reconciler_elected")

        try:
            results = await self.pass_once()
        except Exception:  # one bad pass is not a reason to stop reconciling
            logger.exception("reconciler_pass_failed")
            return

        try:
            await self._survey_queue()
        except Exception:  # a gauge is never worth stopping convergence for
            logger.warning("queue_survey_failed", exc_info=True)

        breaches = [result for result in results if result.floor_breached]
        if breaches:
            # NR-NF-08. Reported at warning rather than raised: the pass that
            # *starts* the first replica necessarily observes zero, so this is a
            # condition to watch across passes, not a fault to fail on.
            logger.warning(
                "serving_floor_breached",
                extra={"deployments": [str(result.deployment_id) for result in breaches]},
            )

    async def pass_once(self) -> list[ConvergenceResult]:
        """One sweep of every tenant with a deployment.

        Serial, deliberately. `apply` shells out to `docker compose`, and a
        parallel sweep would run N of those against one daemon to save time
        nobody is waiting for.
        """
        results: list[ConvergenceResult] = []
        for tenant_id, status in await self._tenants():
            token = tenant_id_var.set(str(tenant_id))
            try:
                result = await self._converge_tenant(
                    tenant_id, suspended=status != TenantStatus.ACTIVE.value
                )
            except Exception:
                # Per tenant, so one unreachable daemon does not strand every
                # other tenant's activation behind it.
                logger.exception("converge_failed", extra={"tenant_id": str(tenant_id)})
                continue
            finally:
                tenant_id_var.reset(token)
            if result is not None:
                results.append(result)
                _publish_replicas(tenant_id, result)
        return results

    async def _survey_queue(self) -> None:
        """Publish queue depth and the age of the oldest queued job.

        Here rather than in the job worker, and for the same reason the replica
        gauges are here: the reconciler is a singleton by election, so there is
        exactly one publisher. Two workers each publishing "the depth is 40"
        would give Prometheus two series that a rule has to `max()` over, and
        would report 40 for a queue that had drained the moment one of them
        stopped scraping.

        Read as the platform role, which holds `SELECT` on six columns of `jobs`
        across every tenant (migration 0006) and cannot read a payload. A survey
        that needed the tenant role would have to be run once per tenant.

        Depth *and* age, because depth alone cannot tell a busy queue from a
        stuck one: forty jobs arriving and draining looks exactly like forty
        jobs nobody has claimed, until you ask how old the oldest one is.
        """
        async with self._platform_sessionmaker() as session:
            depths = await session.execute(
                sa.select(Job.job_type, Job.status, sa.func.count())
                .where(Job.status.in_([QueueStatus.QUEUED.value, QueueStatus.RUNNING.value]))
                .group_by(Job.job_type, Job.status)
            )
            observed = {(row[0], row[1]): row[2] for row in depths.all()}

            oldest = await session.execute(
                sa.select(Job.job_type, sa.func.min(Job.created_at))
                .where(Job.status == QueueStatus.QUEUED.value)
                .group_by(Job.job_type)
            )
            waiting = {row[0]: row[1] for row in oldest.all()}

        now = dt.datetime.now(dt.UTC)
        # Every known job type is written on every pass, including the ones with
        # nothing queued. A gauge that is only written when it is non-zero stays
        # at its last value forever, so a queue that drained would keep alerting
        # and a queue that never had work would silently have no series at all.
        for job_type in JobType:
            for status in (QueueStatus.QUEUED, QueueStatus.RUNNING):
                JOB_QUEUE_DEPTH.labels(job_type=job_type.value, status=status.value).set(
                    observed.get((job_type.value, status.value), 0)
                )
            since = waiting.get(job_type.value)
            JOB_QUEUE_OLDEST_SECONDS.labels(job_type=job_type.value).set(
                (now - since).total_seconds() if since is not None else 0.0
            )

    async def _tenants(self) -> list[tuple[uuid.UUID, str]]:
        """Every tenant with a deployment row, and its lifecycle status.

        Ordered by id so a pass is reproducible and a log from two runs can be
        compared line for line. There is one row per tenant
        (`uq_model_deployments_tenant`), so this is the tenant list and not a
        distinct over something larger.

        The status comes along because a suspended tenant's serving must stop
        (L1417) and the platform role cannot write `model_deployments` to make
        that happen. It reads the status here and the convergence acts on it,
        which keeps the one privilege that can scale a deployment in the one
        process that is allowed to.
        """
        async with self._platform_sessionmaker() as session:
            rows = await session.execute(
                sa.select(ModelDeployment.tenant_id, Tenant.status)
                .join(Tenant, Tenant.tenant_id == ModelDeployment.tenant_id)
                .order_by(ModelDeployment.tenant_id)
            )
            return [(row.tenant_id, row.status) for row in rows.all()]

    async def _converge_tenant(
        self, tenant_id: uuid.UUID, *, suspended: bool
    ) -> ConvergenceResult | None:
        """One tenant, one transaction, under that tenant's own RLS view.

        The deployment is re-read here rather than carried from the sweep: the
        sweep read it as the platform role, which is granted six columns, and
        `converge` needs the row.
        """
        async with self._sessionmaker() as session, session.begin():
            await bind_tenant(session, tenant_id)
            deployment = await self._deployments.find(session)
            if deployment is None:
                # Deleted between the sweep and now. Nothing to converge, and
                # nothing that needs saying about it.
                return None
            return await converge(
                session,
                driver=self._driver,
                deployment=deployment,
                deployments=self._deployments,
                activation_timeout=self._activation_timeout,
                suspended=suspended,
            )

    async def _sleep(self) -> None:
        """Interruptible. `wait_for` on the stop event rather than `sleep`, so a
        `SIGTERM` during the gap exits now instead of at the end of it."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=self._interval)


def _publish_replicas(tenant_id: uuid.UUID, result: ConvergenceResult) -> None:
    """The gauges behind §24's "`ready < 1` for an active tenant" alert.

    Published from the reconciler rather than from the replicas themselves,
    because the number the alert is about is *zero* ready replicas, and zero
    replicas publish nothing. A gauge that can only be written by the thing it
    describes cannot report that the thing is gone.

    `tenant_id` as a label is the one identifier in the whole metric set. It is
    unavoidable — the alert is per tenant — and it is bounded by the estate,
    which is a number an operator can name. Prometheus is on the private network
    (§9.1) and is not a tenant-facing surface.
    """
    labels = SERVING_REPLICAS.labels
    labels(tenant_id=str(tenant_id), state="desired").set(result.desired_replicas)
    labels(tenant_id=str(tenant_id), state="ready").set(result.ready_replicas)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    start_metrics_server(settings, app="reconciler")

    driver = build_serving_driver(
        settings.serving_driver, compose_file=settings.serving_compose_file
    )
    logger.info(
        "reconciler_starting",
        extra={
            "driver": driver.describe().kind,
            "interval_seconds": settings.reconcile_interval_seconds,
            "activation_timeout_seconds": settings.activation_timeout_seconds,
        },
    )

    # The worker engine, not the request one: a convergence pass waits on
    # `docker compose up`, which is minutes of wall clock at the wrong end of a
    # 15-second statement timeout.
    engine = create_worker_engine(settings)
    platform_engine = create_platform_engine(settings)

    reconciler = Reconciler(
        sessionmaker=create_sessionmaker(engine),
        platform_sessionmaker=create_sessionmaker(platform_engine),
        driver=driver,
        interval_seconds=settings.reconcile_interval_seconds,
        activation_timeout=dt.timedelta(seconds=settings.activation_timeout_seconds),
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, reconciler.request_stop)

    try:
        await reconciler.run()
    finally:
        await engine.dispose()
        await platform_engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
