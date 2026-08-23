"""Reads over the deployment, and the one write that changes desired state.

`DeploymentService` answers `GET /v1/deployment*` and owns the only method that
moves `desired_version_id`. Everything that moves `active_version_id` is in
`activation` and `reconciler`, which is the separation ER-F-06 needs: a request
may ask, and only an observation may swap.

**The deployment row is created lazily, on the first activation.** A tenant who
has never trained has nothing to deploy, and a row that said `stopped / 0 / 0`
for every registered tenant would make `/admin/status` count deployments that
are not deployments.

**Nothing here writes `ready_replicas`.** That number is the reconciler's, read
from the driver. A service method that recomputed it from `serving_replicas`
would be reporting the last observation one layer further from the truth, and
the two would disagree exactly when it mattered.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.enums import DeploymentState, ModelVersionStatus
from graphrec.common.errors import ConflictError, NotFoundError
from graphrec.db.models import (
    DeploymentRevision,
    ModelDeployment,
    ModelVersion,
    ServingReplica,
)
from graphrec.serving.states import RevisionStatus

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: The floor NR-NF-08 states, restated as the number a deployment asks for when
#: it is asked to serve at all. A tenant's plan may raise `max_replicas`; it may
#: not lower this, because a deployment that wanted zero would satisfy
#: `ready >= 1` vacuously and serve nothing.
MINIMUM_DESIRED_REPLICAS = 1


@dataclass(frozen=True, slots=True)
class DeploymentView:
    """What `GET /v1/deployment` renders (dc.html L1826-1843).

    A dataclass rather than the ORM row because the page shows the version
    *number* and the row holds an id, and resolving that in the router would put
    a query in a place that has no session of its own.
    """

    deployment_id: uuid.UUID
    state: DeploymentState
    active_version_id: uuid.UUID | None
    active_version_number: int | None
    desired_version_id: uuid.UUID | None
    desired_version_number: int | None
    desired_replicas: int
    ready_replicas: int
    min_replicas: int
    max_replicas: int
    target_rps_per_replica: float
    last_transition_at: dt.datetime | None
    epoch: int

    @property
    def serving_previous(self) -> bool:
        """ER-F-06, on the wire. The console shows it as the difference between
        the version badge and the desired version."""
        return (
            self.active_version_id is not None
            and self.desired_version_id is not None
            and self.active_version_id != self.desired_version_id
        )


class DeploymentService:
    """Everything `/v1/deployment*` needs, and the desired-state write."""

    async def find(self, session: AsyncSession) -> ModelDeployment | None:
        """The tenant's deployment, or `None`. RLS makes "the tenant's" the
        only thing this can return."""
        found: ModelDeployment | None = await session.scalar(sa.select(ModelDeployment).limit(1))
        return found

    async def require(self, session: AsyncSession) -> ModelDeployment:
        """A `404` when the tenant has never deployed.

        Not an empty `available/0/0` view: "no deployment" and "a deployment
        with nothing running" are different states, and a tenant debugging the
        second should not be shown the first.
        """
        found = await self.find(session)
        if found is None:
            raise NotFoundError("not_found")
        return found

    async def ensure(
        self, session: AsyncSession, *, tenant_id: uuid.UUID, model_id: uuid.UUID
    ) -> ModelDeployment:
        """Get it, or create it stopped.

        `UNIQUE (tenant_id)` is what makes this safe under a race: two
        concurrent activations both reach here, one inserts and the other is
        refused by the constraint. The refusal surfaces as an integrity error
        the caller's transaction rolls back, which is the correct outcome —
        `activate` also refuses a concurrent activation explicitly, and this is
        the belt behind that brace.
        """
        found = await self.find(session)
        if found is not None:
            return found
        deployment = ModelDeployment(
            tenant_id=tenant_id,
            model_id=model_id,
            state=DeploymentState.STOPPED.value,
            desired_replicas=0,
            ready_replicas=0,
        )
        session.add(deployment)
        await session.flush()
        return deployment

    # ------------------------------------------------------------------ reads

    async def view(self, session: AsyncSession) -> DeploymentView:
        """The deployment with version numbers resolved.

        One extra query for up to two versions, batched — the page renders both
        and asking twice is how they come to be read at different instants.
        """
        deployment = await self.require(session)
        wanted = {
            value
            for value in (deployment.active_version_id, deployment.desired_version_id)
            if value is not None
        }
        numbers = await self._version_numbers(session, wanted)
        return DeploymentView(
            deployment_id=deployment.deployment_id,
            state=deployment.deployment_state,
            active_version_id=deployment.active_version_id,
            active_version_number=numbers.get(deployment.active_version_id),
            desired_version_id=deployment.desired_version_id,
            desired_version_number=numbers.get(deployment.desired_version_id),
            desired_replicas=deployment.desired_replicas,
            ready_replicas=deployment.ready_replicas,
            min_replicas=deployment.min_replicas,
            max_replicas=deployment.max_replicas,
            target_rps_per_replica=float(deployment.target_rps_per_replica),
            last_transition_at=deployment.last_transition_at,
            epoch=deployment.epoch,
        )

    async def replicas(self, session: AsyncSession) -> list[ServingReplica]:
        """The per-replica table at L1832, newest first.

        Includes stopped and failed rows. A replica that died two minutes ago is
        the row someone reading this page came for; pruning is the reconciler's,
        and it prunes what the driver no longer reports rather than what looks
        finished.
        """
        rows = await session.scalars(
            sa.select(ServingReplica).order_by(ServingReplica.started_at.desc())
        )
        return list(rows.all())

    async def revisions(
        self, session: AsyncSession, *, limit: int = 20
    ) -> list[DeploymentRevision]:
        """The activation history, newest first — including the failures."""
        rows = await session.scalars(
            sa.select(DeploymentRevision).order_by(DeploymentRevision.revision.desc()).limit(limit)
        )
        return list(rows.all())

    async def pending_revision(self, session: AsyncSession) -> DeploymentRevision | None:
        """The one in flight, if any. At most one by construction — `activate`
        refuses to open a second."""
        found: DeploymentRevision | None = await session.scalar(
            sa.select(DeploymentRevision)
            .where(DeploymentRevision.status == RevisionStatus.PENDING.value)
            .order_by(DeploymentRevision.revision.desc())
            .limit(1)
        )
        return found

    # ----------------------------------------------------------------- writes

    async def set_desired(
        self,
        session: AsyncSession,
        *,
        deployment: ModelDeployment,
        version_id: uuid.UUID,
        replicas: int | None = None,
        state: DeploymentState = DeploymentState.PROGRESSING,
        now: dt.datetime | None = None,
    ) -> ModelDeployment:
        """Move desired state and bump the epoch.

        The epoch bump is the point. A replica started for epoch 4 that is still
        running when the deployment is on epoch 5 is drift the reconciler can
        see; without the bump it would be a container running the right version
        for the wrong reason, indistinguishable from a healthy one.

        `active_version_id` is untouched here, always. That is the invariant
        ER-F-06 rests on and the reason this method exists rather than a general
        update.
        """
        deployment.desired_version_id = version_id
        deployment.desired_replicas = max(
            replicas if replicas is not None else deployment.min_replicas,
            MINIMUM_DESIRED_REPLICAS,
        )
        deployment.state = state.value
        deployment.epoch += 1
        deployment.updated_at = now or dt.datetime.now(dt.UTC)
        await session.flush()
        logger.info(
            "deployment_desired_changed",
            extra={
                "deployment_id": str(deployment.deployment_id),
                "epoch": deployment.epoch,
                "desired_replicas": deployment.desired_replicas,
            },
        )
        return deployment

    async def next_revision_number(self, session: AsyncSession, *, deployment_id: uuid.UUID) -> int:
        """`max + 1` inside the caller's transaction.

        `UNIQUE (deployment_id, revision)` is what makes the race safe: two
        callers computing 4 means one of them fails to insert, which is the
        outcome a concurrent activation should have anyway.
        """
        current = await session.scalar(
            sa.select(sa.func.max(DeploymentRevision.revision)).where(
                DeploymentRevision.deployment_id == deployment_id
            )
        )
        return int(current or 0) + 1

    async def settle_revision(
        self,
        session: AsyncSession,
        *,
        revision: DeploymentRevision,
        status: RevisionStatus,
        failure_reason: str | None = None,
        now: dt.datetime | None = None,
    ) -> DeploymentRevision:
        """Close a revision. `pending` is not a settlement and is refused."""
        if status is RevisionStatus.PENDING:
            msg = "a revision settles into succeeded or failed"
            raise ConflictError("invalid_state", reason=msg)
        revision.status = status.value
        revision.failure_reason = failure_reason if status is RevisionStatus.FAILED else None
        revision.completed_at = now or dt.datetime.now(dt.UTC)
        await session.flush()
        return revision

    async def _version_numbers(
        self, session: AsyncSession, version_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID | None, int]:
        if not version_ids:
            return {}
        rows = await session.execute(
            sa.select(ModelVersion.model_version_id, ModelVersion.version_number).where(
                ModelVersion.model_version_id.in_(version_ids)
            )
        )
        return dict(rows.all())  # type: ignore[arg-type]


async def rollback_target(session: AsyncSession, *, active_number: int) -> ModelVersion | None:
    """The retained version a rollback would go to (ER-F-07).

    The highest-numbered `retired` version below the active one, which under the
    archive rule at dc.html L1749 is exactly the one that was protected from
    archiving. Asking for "the previous version" by subtracting one would break
    the moment a version between them was archived — the protection is stated as
    an inequality precisely because the numbering has holes in it.
    """
    found: ModelVersion | None = await session.scalar(
        sa.select(ModelVersion)
        .where(
            ModelVersion.status == ModelVersionStatus.RETIRED.value,
            ModelVersion.version_number < active_number,
        )
        .order_by(ModelVersion.version_number.desc())
        .limit(1)
    )
    return found


__all__ = [
    "MINIMUM_DESIRED_REPLICAS",
    "DeploymentService",
    "DeploymentView",
    "rollback_target",
]
