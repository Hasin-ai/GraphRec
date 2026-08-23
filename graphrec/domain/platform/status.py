"""`GET /v1/platform/status` — the installation's health, gaps included.

UC-30's alternative outcome is the whole specification of this module:
*"Measurement gaps are identified rather than hidden."* Every quantity here is
therefore nullable, and every null is accompanied by a named gap carrying a
sentence. The console renders a gap as the literal string `gap` in warn colour
(L1531, L1537), which only works if the server is willing to say it has no
number — a board that substituted `0` would render a healthy-looking zero for
an installation whose reconciler died an hour ago.

Two quantities can legitimately have no value, and they fail for opposite
reasons:

* **`serving_availability`** is a ratio, and a window with no requests has no
  denominator. That is not a fault; nothing was served, so nothing can be said
  about how well it was served.
* **`replicas.ready`** is a *mirror* of what the reconciler last observed. When
  the reconciler has not run recently the row is still there and still holds
  numbers, and those numbers are the most dangerous thing on this page: they
  look like an observation and are a memory. Staleness is checked against
  `last_transition_at` and reported as a gap rather than rendered.

Everything else — queue depths, failure counts, the tenant roll — is a count of
rows that either exist or do not, and a count of zero rows is a measurement.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.enums import TenantStatus
from graphrec.common.error_copy import MEASUREMENT_GAP_COPY
from graphrec.db.models import Job, ModelDeployment, RecommendationRequest, SecurityEvent, Tenant
from graphrec.jobs.states import JobType, QueueStatus

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

#: The board's default window. Matches `failures_24h`, which is named for it.
DEFAULT_WINDOW = dt.timedelta(hours=24)

#: How long a deployment observation stays trustworthy. The reconciler's
#: interval is seconds, so five minutes is many missed passes rather than one
#: slow one — this must not flap when a single convergence takes a while.
DEFAULT_STALENESS = dt.timedelta(minutes=5)

#: `recommendation_requests.status` values that count as served. The column is
#: granted to the platform role; the payload columns beside it are not.
SERVED_STATUS = "succeeded"


@dataclass(frozen=True, slots=True)
class MeasurementGap:
    """A quantity that has no value, and the sentence explaining why."""

    quantity: str
    reason: str


@dataclass(frozen=True, slots=True)
class QueueDepth:
    """Training, which is globally serialised (ASM-03).

    `concurrency` is the configured ceiling rather than an observation, and it
    is on this board because `waiting: 6` means something different at a
    concurrency of one than at a concurrency of eight.
    """

    running: int
    waiting: int
    concurrency: int


@dataclass(frozen=True, slots=True)
class ReplicaCount:
    ready: int | None
    desired: int


@dataclass(frozen=True, slots=True)
class TenantWorkload:
    """What one tenant is currently costing the installation (UC-30)."""

    tenant_id: uuid.UUID
    tenant_code: str
    running_jobs: int
    queued_jobs: int
    desired_replicas: int
    ready_replicas: int


@dataclass(frozen=True, slots=True)
class FailureSummaryRow:
    area: str
    severity: str
    count: int


@dataclass(frozen=True, slots=True)
class PlatformStatus:
    window_hours: int
    serving_availability: float | None
    training_queue: QueueDepth
    replicas: ReplicaCount
    ingestion_lag_seconds: int
    failures_24h: int
    active_tenants: int
    workload_by_tenant: list[TenantWorkload]
    failure_summary: list[FailureSummaryRow]
    measurement_gaps: list[MeasurementGap] = field(default_factory=list)


async def platform_status(
    session: AsyncSession,
    *,
    training_concurrency: int,
    window: dt.timedelta = DEFAULT_WINDOW,
    staleness: dt.timedelta = DEFAULT_STALENESS,
    now: dt.datetime | None = None,
) -> PlatformStatus:
    """Six readings, assembled. Each is independent by design.

    They are separate queries rather than one composed statement because they
    read five tables with three different shapes, and a join that produced them
    together would make one slow table the latency of the whole board. The cost
    is that the readings are from slightly different instants, which matters for
    none of them: nothing here is a ratio computed across two queries.
    """
    moment = now or dt.datetime.now(dt.UTC)
    since = moment - window
    gaps: list[MeasurementGap] = []

    availability = await _availability(session, since=since)
    if availability is None:
        gaps.append(_gap("serving_availability"))

    queue = await _training_queue(session, concurrency=training_concurrency)
    replicas, replicas_stale = await _replicas(session, now=moment, staleness=staleness)
    if replicas_stale:
        gaps.append(_gap("replicas"))

    return PlatformStatus(
        window_hours=int(window.total_seconds() // 3600),
        serving_availability=availability,
        training_queue=queue,
        replicas=replicas,
        ingestion_lag_seconds=await _ingestion_lag(session, now=moment),
        failures_24h=await _failure_count(session, since=since),
        active_tenants=await _active_tenants(session),
        workload_by_tenant=await _workload(session),
        failure_summary=await _failure_summary(session, since=since),
        measurement_gaps=gaps,
    )


async def _availability(session: AsyncSession, *, since: dt.datetime) -> float | None:
    """Served over attempted, on the six columns the platform role may read."""
    row = (
        await session.execute(
            sa.select(
                sa.func.count().label("total"),
                sa.func.count()
                .filter(RecommendationRequest.status == SERVED_STATUS)
                .label("served"),
            ).where(RecommendationRequest.requested_at >= since)
        )
    ).one()
    if not row.total:
        return None
    return round(float(row.served) / float(row.total), 4)


async def _training_queue(session: AsyncSession, *, concurrency: int) -> QueueDepth:
    result = await session.execute(
        sa.select(Job.status, sa.func.count())
        .where(
            Job.job_type == JobType.TRAINING.value,
            Job.status.in_((QueueStatus.RUNNING.value, QueueStatus.QUEUED.value)),
        )
        .group_by(Job.status)
    )
    counts: dict[str, int] = {status: int(count) for status, count in result.all()}
    return QueueDepth(
        running=counts.get(QueueStatus.RUNNING.value, 0),
        waiting=counts.get(QueueStatus.QUEUED.value, 0),
        concurrency=concurrency,
    )


async def _replicas(
    session: AsyncSession, *, now: dt.datetime, staleness: dt.timedelta
) -> tuple[ReplicaCount, bool]:
    """Ready and desired across every deployment, and whether ready is stale."""
    row = (
        await session.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(ModelDeployment.desired_replicas), 0),
                sa.func.coalesce(sa.func.sum(ModelDeployment.ready_replicas), 0),
                sa.func.max(ModelDeployment.last_transition_at),
                sa.func.count(),
            )
        )
    ).one()
    desired, ready, latest, deployments = int(row[0]), int(row[1]), row[2], int(row[3])

    if deployments == 0:
        # Nothing is deployed. Zero ready of zero desired is a measurement, not
        # a gap: there is no observation missing, there is nothing to observe.
        return ReplicaCount(ready=0, desired=0), False
    if latest is None or (now - latest) > staleness:
        return ReplicaCount(ready=None, desired=desired), True
    return ReplicaCount(ready=ready, desired=desired), False


async def _ingestion_lag(session: AsyncSession, *, now: dt.datetime) -> int:
    """How long the oldest waiting ingestion job has been waiting, in seconds.

    Measured from `run_after` rather than `created_at`, because a job that asked
    to be deferred is not late until the time it asked for. An empty queue is
    zero seconds of lag, which is a measurement: nothing is waiting.
    """
    oldest = await session.scalar(
        sa.select(sa.func.min(Job.run_after)).where(
            Job.status == QueueStatus.QUEUED.value,
            Job.job_type.in_([t.value for t in (JobType.EVENT_BATCH, JobType.PRODUCT_BULK_UPSERT)]),
        )
    )
    if oldest is None:
        return 0
    return max(int((now - oldest).total_seconds()), 0)


async def _failure_count(session: AsyncSession, *, since: dt.datetime) -> int:
    total = await session.scalar(
        sa.select(sa.func.count())
        .select_from(SecurityEvent)
        .where(SecurityEvent.occurred_at >= since)
    )
    return int(total or 0)


async def _active_tenants(session: AsyncSession) -> int:
    total = await session.scalar(
        sa.select(sa.func.count())
        .select_from(Tenant)
        .where(Tenant.status == TenantStatus.ACTIVE.value)
    )
    return int(total or 0)


async def _workload(session: AsyncSession) -> list[TenantWorkload]:
    """Per-tenant load: jobs in flight and replicas held.

    Only tenants that are currently costing something appear. A roll of every
    tenant with four zeros would grow with the estate and say nothing, and the
    operator opening this board is looking for the tenant that is busy.
    """
    jobs = (
        sa.select(
            Job.tenant_id,
            sa.func.count().filter(Job.status == QueueStatus.RUNNING.value).label("running"),
            sa.func.count().filter(Job.status == QueueStatus.QUEUED.value).label("queued"),
        )
        .where(Job.status.in_((QueueStatus.RUNNING.value, QueueStatus.QUEUED.value)))
        .group_by(Job.tenant_id)
        .subquery()
    )
    deployments = (
        sa.select(
            ModelDeployment.tenant_id,
            sa.func.sum(ModelDeployment.desired_replicas).label("desired"),
            sa.func.sum(ModelDeployment.ready_replicas).label("ready"),
        )
        .where(ModelDeployment.desired_replicas > 0)
        .group_by(ModelDeployment.tenant_id)
        .subquery()
    )
    result = await session.execute(
        sa.select(
            Tenant.tenant_id,
            Tenant.tenant_code,
            sa.func.coalesce(jobs.c.running, 0),
            sa.func.coalesce(jobs.c.queued, 0),
            sa.func.coalesce(deployments.c.desired, 0),
            sa.func.coalesce(deployments.c.ready, 0),
        )
        .join(jobs, jobs.c.tenant_id == Tenant.tenant_id, isouter=True)
        .join(deployments, deployments.c.tenant_id == Tenant.tenant_id, isouter=True)
        .where(sa.or_(jobs.c.tenant_id.is_not(None), deployments.c.tenant_id.is_not(None)))
        .order_by(Tenant.tenant_code)
    )
    return [
        TenantWorkload(
            tenant_id=row[0],
            tenant_code=row[1],
            running_jobs=int(row[2]),
            queued_jobs=int(row[3]),
            desired_replicas=int(row[4]),
            ready_replicas=int(row[5]),
        )
        for row in result.all()
    ]


async def _failure_summary(session: AsyncSession, *, since: dt.datetime) -> list[FailureSummaryRow]:
    result = await session.execute(
        sa.select(SecurityEvent.area, SecurityEvent.severity, sa.func.count())
        .where(SecurityEvent.occurred_at >= since)
        .group_by(SecurityEvent.area, SecurityEvent.severity)
        .order_by(SecurityEvent.area, SecurityEvent.severity)
    )
    return [
        FailureSummaryRow(area=area, severity=severity, count=int(count))
        for area, severity, count in result.all()
    ]


def _gap(quantity: str) -> MeasurementGap:
    return MeasurementGap(quantity=quantity, reason=MEASUREMENT_GAP_COPY[quantity])


__all__ = [
    "DEFAULT_STALENESS",
    "DEFAULT_WINDOW",
    "FailureSummaryRow",
    "MeasurementGap",
    "PlatformStatus",
    "QueueDepth",
    "ReplicaCount",
    "TenantWorkload",
    "platform_status",
]
