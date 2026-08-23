"""Desired state meets observed state, and the swap that only happens on proof.

One function does the work — `converge` — and it is deliberately callable
outside the loop that normally calls it. The loop belongs to `apps.reconciler`;
the decision belongs here, and a decision that could only be exercised by
running a daemon is a decision that is never tested.

**The leader lock is a PostgreSQL session advisory lock.** ADR 0028: two
reconcilers converging one tenant would both call `apply` with different epochs
and fight over the replica count. `pg_try_advisory_lock` is the right primitive
because it is held by a *session* and released when that session dies — a
reconciler killed mid-pass releases the lock without anyone having to notice it
died, which a lease row in a table does not do.

**The swap requires a ready replica answering with the new version.** Not "the
driver accepted the apply", not "a container exists" — `observation.serving(
desired) >= 1`. That is the whole of ER-F-06: until that number is one, the
previous version is still `active` and still answering, and if it never reaches
one the activation fails with the previous version untouched.

**A failed activation marks the version, not just the attempt.**
`failed_deployment` is a distinct status from `rejected` for the reason ADR 0027
gives: one means the model was measured and found wanting, the other means it
was good and would not load. A tenant retraining after a `rejected` is doing
something sensible; a tenant retraining after a `failed_deployment` is treating
an operational fault as a modelling one.

**`ready >= 1` is enforced here and nowhere else.** It is not a database check —
there is a legitimate window, between `apply` and the first container becoming
healthy, in which it is false. It is a floor the convergence loop restores, and
`floor_breaches` is what a test asserts on.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.enums import DeploymentState, ModelVersionStatus
from graphrec.common.error_copy import resolve_copy
from graphrec.db.models import (
    ModelActivationHistory,
    ModelVersion,
    ServingReplica,
)
from graphrec.domain.serving.deployment import DeploymentService
from graphrec.serving.states import RevisionStatus
from graphrec.serving_driver.driver import DesiredState, DriverError

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.db.models import DeploymentRevision, ModelDeployment
    from graphrec.serving_driver.driver import Observation, ServingDriver

logger = logging.getLogger(__name__)

#: The advisory-lock namespace. Two 32-bit halves; this is the first, so a
#: future lock for another purpose can use its own without colliding. The value
#: is arbitrary and only has to be stable — changing it would let an old process
#: and a new one both believe they are leader.
LOCK_NAMESPACE = 0x47524543  # "GREC"

#: The second half, identifying the reconciler's leadership specifically.
LOCK_KEY = 1

#: How long an activation may sit `progressing` before it is a failure. Long
#: enough for an image pull on a cold host; short enough that a tenant watching
#: the console is not left with a spinner for the afternoon. Passed in rather
#: than read from `Settings` here, because the domain does not read settings.
DEFAULT_ACTIVATION_TIMEOUT = dt.timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class ConvergenceResult:
    """What one pass did. Everything a test or a log line needs.

    `swapped` and `failed` are separate booleans rather than one enum because a
    pass can do neither — the common case, where the deployment is already where
    it should be — and an enum would need a value for "nothing happened" that
    reads as an outcome.
    """

    deployment_id: uuid.UUID
    state: DeploymentState
    desired_replicas: int
    ready_replicas: int
    swapped: bool = False
    failed: bool = False
    #: True when the deployment wanted replicas and had none ready at the end of
    #: the pass. NR-NF-08's floor, reported rather than asserted — the pass that
    #: *starts* the first replica necessarily observes zero.
    floor_breached: bool = False
    detail: str | None = None


async def acquire_leadership(session: AsyncSession) -> bool:
    """Try to become the reconciler. Non-blocking.

    `pg_try_advisory_lock` rather than `pg_advisory_lock`: a follower should
    return immediately and sleep, not hold a connection open waiting for the
    leader to die. The lock lives on this session, so it is released by
    `release_leadership`, by closing the connection, or by the process
    disappearing — all three of which are outcomes a supervisor produces.
    """
    acquired = await session.scalar(
        sa.select(sa.func.pg_try_advisory_lock(LOCK_NAMESPACE, LOCK_KEY))
    )
    return bool(acquired)


async def release_leadership(session: AsyncSession) -> None:
    """Give it up. Idempotent from the caller's point of view — unlocking a lock
    this session does not hold logs a warning in PostgreSQL and returns false,
    which is not a condition worth raising on during shutdown."""
    with contextlib.suppress(Exception):
        await session.execute(sa.select(sa.func.pg_advisory_unlock(LOCK_NAMESPACE, LOCK_KEY)))


async def converge(
    session: AsyncSession,
    *,
    driver: ServingDriver,
    deployment: ModelDeployment,
    deployments: DeploymentService | None = None,
    activation_timeout: dt.timedelta = DEFAULT_ACTIVATION_TIMEOUT,
    now: dt.datetime | None = None,
) -> ConvergenceResult:
    """One pass over one tenant: apply, observe, record, decide.

    The order matters. `apply` before `observe` so the observation reflects this
    pass rather than the last; the replica rows written before the decision so
    that a crash between the two leaves `/service-status` honest; the swap last,
    because it is the only irreversible thing here.
    """
    service = deployments or DeploymentService()
    moment = now or dt.datetime.now(dt.UTC)

    if deployment.desired_version_id is None or deployment.desired_replicas == 0:
        # Nothing is wanted. Observe anyway — a tenant whose deployment was
        # stopped may still have containers the driver knows about, and leaving
        # them unrecorded is how a replica outlives the row that explains it.
        observation = await _observe(driver, deployment)
        await _record_replicas(session, deployment=deployment, observation=observation, now=moment)
        return ConvergenceResult(
            deployment_id=deployment.deployment_id,
            state=deployment.deployment_state,
            desired_replicas=deployment.desired_replicas,
            ready_replicas=deployment.ready_replicas,
        )

    version = await session.get(ModelVersion, deployment.desired_version_id)
    if version is None:  # pragma: no cover - `RESTRICT` makes this unreachable
        msg = "desired version row is missing"
        raise RuntimeError(msg)

    desired = DesiredState(
        tenant_id=deployment.tenant_id,
        version_id=deployment.desired_version_id,
        bundle_uri=version.artifact_uri,
        replicas=deployment.desired_replicas,
        epoch=deployment.epoch,
    )
    try:
        observation = await driver.apply(desired)
    except DriverError as exc:
        # The orchestrator could not be reached. Not a failed activation: the
        # next pass may well succeed, and marking the version `failed_deployment`
        # for a transient docker socket would spend a tenant's version on an
        # infrastructure hiccup. The deadline below is what eventually decides.
        logger.warning(
            "reconcile_driver_unavailable",
            extra={"deployment_id": str(deployment.deployment_id), "detail": str(exc)},
        )
        return ConvergenceResult(
            deployment_id=deployment.deployment_id,
            state=deployment.deployment_state,
            desired_replicas=deployment.desired_replicas,
            ready_replicas=deployment.ready_replicas,
            floor_breached=deployment.ready_replicas < 1,
            detail=str(exc),
        )

    await _record_replicas(session, deployment=deployment, observation=observation, now=moment)
    deployment.ready_replicas = observation.ready_count
    deployment.updated_at = moment

    serving_desired = observation.serving(deployment.desired_version_id)
    revision = await service.pending_revision(session)

    if serving_desired >= 1 and deployment.active_version_id != deployment.desired_version_id:
        return await _swap(
            session,
            service=service,
            deployment=deployment,
            revision=revision,
            now=moment,
        )

    if revision is not None and _timed_out(revision, now=moment, timeout=activation_timeout):
        return await _fail_activation(
            session, service=service, deployment=deployment, revision=revision, now=moment
        )

    # Steady state, or still settling. `available` only when the desired version
    # is the active one and something is ready; `degraded` when a deployment
    # that should be serving has nothing ready and is not mid-activation.
    if deployment.active_version_id == deployment.desired_version_id:
        deployment.state = (
            DeploymentState.AVAILABLE.value
            if observation.ready_count >= 1
            else DeploymentState.DEGRADED.value
        )
    await session.flush()
    return ConvergenceResult(
        deployment_id=deployment.deployment_id,
        state=deployment.deployment_state,
        desired_replicas=deployment.desired_replicas,
        ready_replicas=deployment.ready_replicas,
        floor_breached=deployment.ready_replicas < 1,
    )


# --------------------------------------------------------------------- pieces


async def _observe(driver: ServingDriver, deployment: ModelDeployment) -> Observation:
    try:
        return await driver.observe(deployment.tenant_id)
    except DriverError:
        from graphrec.serving_driver.driver import Observation as _Observation

        return _Observation(tenant_id=deployment.tenant_id)


async def _record_replicas(
    session: AsyncSession,
    *,
    deployment: ModelDeployment,
    observation: Observation,
    now: dt.datetime,
) -> None:
    """Mirror the driver into `serving_replicas`.

    Upsert by `replica_ref`, then delete the rows the driver no longer reports.
    Deleting rather than marking stopped: this table is a mirror, and a row for
    a container that no longer exists is not history, it is a lie with a
    timestamp on it. The revisions table is where history lives.
    """
    existing = {
        row.replica_ref: row
        for row in (
            await session.scalars(
                sa.select(ServingReplica).where(
                    ServingReplica.deployment_id == deployment.deployment_id
                )
            )
        ).all()
    }
    seen: set[str] = set()
    for replica in observation.replicas:
        seen.add(replica.replica_ref)
        terminal = replica.status in _TERMINAL_REPLICA_STATUSES
        row = existing.get(replica.replica_ref)
        if row is None:
            row = ServingReplica(
                tenant_id=deployment.tenant_id,
                deployment_id=deployment.deployment_id,
                replica_ref=replica.replica_ref,
                started_at=replica.started_at or now,
            )
            session.add(row)
        row.version_id = replica.version_id
        row.status = replica.status.value
        # `ready` is cleared for a terminal replica regardless of what the
        # driver said. `ck_serving_replicas_ready_not_ended` would refuse the
        # combination anyway; doing it here means the refusal is a decision
        # rather than an integrity error nobody expected.
        row.ready = replica.ready and not terminal
        row.ended_at = now if terminal else None
        row.observed_at = now

    gone = [ref for ref in existing if ref not in seen]
    if gone:
        await session.execute(
            sa.delete(ServingReplica).where(
                ServingReplica.deployment_id == deployment.deployment_id,
                ServingReplica.replica_ref.in_(gone),
            )
        )
    await session.flush()


_TERMINAL_REPLICA_STATUSES = frozenset({"stopped", "failed"})


async def _swap(
    session: AsyncSession,
    *,
    service: DeploymentService,
    deployment: ModelDeployment,
    revision: DeploymentRevision | None,
    now: dt.datetime,
) -> ConvergenceResult:
    """The new version is answering. Make it official.

    Retire before activate, in two flushed statements. `uq_model_versions_one_
    active` is a partial unique index checked per statement, so the other order
    would be refused by PostgreSQL — and relying on SQLAlchemy's flush order to
    get it right is relying on something that is not part of its contract.
    """
    desired_id = deployment.desired_version_id
    if desired_id is None:  # pragma: no cover - the caller checked
        msg = "a swap needs a desired version"
        raise RuntimeError(msg)
    previous_id = deployment.active_version_id

    if previous_id is not None and previous_id != desired_id:
        previous = await session.get(ModelVersion, previous_id)
        if previous is not None:
            # Retained, not archived: this is the rollback target ER-F-07 needs
            # to still be there.
            previous.status = ModelVersionStatus.RETIRED.value
            await session.flush()

    version = await session.get(ModelVersion, desired_id)
    if version is not None:
        version.status = ModelVersionStatus.ACTIVE.value
        # A version that previously failed to deploy and has now loaded keeps no
        # note about it. The revision history is where that attempt lives.
        version.failure_note = None
        await session.flush()

    deployment.active_version_id = desired_id
    deployment.state = DeploymentState.AVAILABLE.value
    deployment.last_transition_at = now
    deployment.updated_at = now

    session.add(
        ModelActivationHistory(
            tenant_id=deployment.tenant_id,
            model_id=deployment.model_id,
            from_version_id=previous_id,
            to_version_id=desired_id,
            actor_id=revision.requested_by if revision else None,
            # A swap with no revision behind it is the reconciler repairing
            # drift, and `system_process` is the honest actor for that.
            actor_type=(revision.requested_by_type if revision else _SYSTEM_ACTOR),
            reason=revision.reason if revision else None,
            occurred_at=now,
        )
    )
    if revision is not None:
        await service.settle_revision(
            session, revision=revision, status=RevisionStatus.SUCCEEDED, now=now
        )
    await session.flush()
    logger.info(
        "deployment_swapped",
        extra={
            "deployment_id": str(deployment.deployment_id),
            "from_version_id": str(previous_id) if previous_id else None,
            "to_version_id": str(desired_id),
        },
    )
    return ConvergenceResult(
        deployment_id=deployment.deployment_id,
        state=deployment.deployment_state,
        desired_replicas=deployment.desired_replicas,
        ready_replicas=deployment.ready_replicas,
        swapped=True,
    )


_SYSTEM_ACTOR = "system_process"


async def _fail_activation(
    session: AsyncSession,
    *,
    service: DeploymentService,
    deployment: ModelDeployment,
    revision: DeploymentRevision,
    now: dt.datetime,
) -> ConvergenceResult:
    """The deadline passed with nothing ready. Put desired state back.

    The previous version was never touched, so "the previous version keeps
    serving" needs no repair — only `desired_version_id` has to be walked back,
    so the next pass does not keep trying to start a bundle that will not load.
    """
    failed_id = deployment.desired_version_id
    previous = None
    if deployment.active_version_id is not None:
        previous = await session.get(ModelVersion, deployment.active_version_id)

    if failed_id is not None and failed_id != deployment.active_version_id:
        version = await session.get(ModelVersion, failed_id)
        if version is not None:
            # ADR 0027: measured and good, but would not load. A different
            # status from `rejected`, and a different thing to tell a tenant.
            version.status = ModelVersionStatus.FAILED_DEPLOYMENT.value
            version.failure_note = _failure_copy(previous)
            await session.flush()

    deployment.desired_version_id = deployment.active_version_id
    deployment.desired_replicas = (
        max(deployment.min_replicas, 1) if deployment.active_version_id is not None else 0
    )
    deployment.state = (
        DeploymentState.AVAILABLE.value
        if deployment.active_version_id is not None and deployment.ready_replicas >= 1
        else DeploymentState.DEGRADED.value
    )
    deployment.epoch += 1
    deployment.last_transition_at = now
    deployment.updated_at = now

    await service.settle_revision(
        session,
        revision=revision,
        status=RevisionStatus.FAILED,
        failure_reason=_failure_copy(previous),
        now=now,
    )
    await session.flush()
    logger.warning(
        "activation_failed",
        extra={
            "deployment_id": str(deployment.deployment_id),
            "model_version_id": str(failed_id) if failed_id else None,
            "retained_version_id": (
                str(deployment.active_version_id) if deployment.active_version_id else None
            ),
        },
    )
    return ConvergenceResult(
        deployment_id=deployment.deployment_id,
        state=deployment.deployment_state,
        desired_replicas=deployment.desired_replicas,
        ready_replicas=deployment.ready_replicas,
        failed=True,
        floor_breached=deployment.active_version_id is not None and deployment.ready_replicas < 1,
    )


def _failure_copy(previous: ModelVersion | None) -> str:
    """The console's own consequence line (dc.html L1779), both halves.

    Which half depends on whether anything was already serving, which is
    exactly the distinction the prototype makes — and the version number in the
    first half is the one that *kept* serving.
    """
    if previous is None:
        return resolve_copy("activation_failed_no_active")
    return resolve_copy("activation_failed", version_number=previous.version_number)


def _timed_out(revision: DeploymentRevision, *, now: dt.datetime, timeout: dt.timedelta) -> bool:
    started = revision.started_at
    if started.tzinfo is None:  # pragma: no cover - the column is timezone-aware
        started = started.replace(tzinfo=dt.UTC)
    return now - started >= timeout


__all__ = [
    "DEFAULT_ACTIVATION_TIMEOUT",
    "LOCK_KEY",
    "LOCK_NAMESPACE",
    "ConvergenceResult",
    "acquire_leadership",
    "converge",
    "release_leadership",
]
