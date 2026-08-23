"""Asking for a version to serve, and asking for the previous one back.

Two entry points, `activate` and `rollback`, and neither of them makes anything
serve. They record an intention: a `deployment_revisions` row, a new
`desired_version_id`, a bumped epoch. The swap happens in `reconciler`, and only
after a replica has been observed answering with the new version.

**That split is load-before-swap (ER-F-06).** If `activate` moved
`active_version_id` and then started containers, a bundle that would not load
would leave the tenant with an active version nothing is serving — the failure
mode the requirement names. Here the worst case is a `desired` that never
becomes `active`, which is a deployment marked `degraded` beside a previous
version still answering every request.

**`rollback` validates the target before it changes anything (ER-F-07).** The
target must exist, be retained rather than archived, and have an artifact the
store can still see. Checking after the desired state moved would mean a
rollback to a version whose bytes are gone leaves the deployment pointed at
nothing.

**The refusals are the console's own sentences.** `lifecycle.can_activate` and
`lifecycle.can_rollback` are the same functions the registry's `actions` block
is built from, so the disabled button and the `409` say the same thing — the
gate-5 rule made structural rather than conventional.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.enums import AuditActor, DeploymentState, ModelVersionStatus
from graphrec.common.errors import ConflictError, NotFoundError
from graphrec.db.models import DeploymentRevision, ModelVersion
from graphrec.domain.registry import lifecycle
from graphrec.domain.serving.deployment import DeploymentService, rollback_target
from graphrec.serving.states import RevisionKind

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.db.models import ModelDeployment
    from graphrec.storage.store import ArtifactStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActivationRequest:
    """What was asked and by whom.

    The actor travels down to `deployment_revisions.requested_by` rather than
    being resolved at swap time, because the swap is minutes later in another
    process and "who activated version 8" must not resolve to the reconciler.
    """

    deployment: ModelDeployment
    revision: DeploymentRevision
    target: ModelVersion


class ActivationService:
    """`:activate` and `:rollback`. Neither one swaps anything."""

    def __init__(self, *, deployments: DeploymentService | None = None) -> None:
        self._deployments = deployments or DeploymentService()

    async def activate(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        version_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        actor_type: AuditActor = AuditActor.TENANT_USER,
        reason: str | None = None,
        now: dt.datetime | None = None,
    ) -> ActivationRequest:
        """Ask for `version_id` to serve.

        Returns with the deployment `progressing` and the previous version — if
        there was one — still active and still answering.
        """
        version = await self._version(session, version_id=version_id)
        decision = lifecycle.can_activate(version.version_status)
        if not decision.allowed:
            raise ConflictError(decision.code or "invalid_state")

        deployment = await self._deployments.ensure(
            session, tenant_id=tenant_id, model_id=version.model_id
        )
        await self._refuse_if_busy(session)

        revision = await self._open_revision(
            session,
            tenant_id=tenant_id,
            deployment=deployment,
            kind=RevisionKind.ACTIVATION,
            to_version_id=version_id,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason,
            now=now,
        )
        await self._deployments.set_desired(
            session,
            deployment=deployment,
            version_id=version_id,
            state=DeploymentState.PROGRESSING,
            now=now,
        )
        logger.info(
            "activation_requested",
            extra={
                "deployment_id": str(deployment.deployment_id),
                "model_version_id": str(version_id),
                "revision": revision.revision,
            },
        )
        return ActivationRequest(deployment=deployment, revision=revision, target=version)

    async def rollback(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        actor_type: AuditActor = AuditActor.TENANT_USER,
        target_version_id: uuid.UUID | None = None,
        reason: str | None = None,
        store: ArtifactStore | None = None,
        now: dt.datetime | None = None,
    ) -> ActivationRequest:
        """Ask for the retained previous version back.

        The server chooses the target; `target_version_id` states which target
        the caller believed it was choosing. BACKEND_PLAN L1166 puts it in the
        body and dc.html L1769 offers exactly one retained target, so the two
        together mean *confirmation*, not selection: a caller naming a different
        retired version is refused with `invalid_target` rather than quietly
        rolled back to the one the server would have picked. A console showing
        "roll back to v7" must not send a request that rolls back to v6 because
        v7 was archived while the dialog was open.
        """
        deployment = await self._deployments.require(session)
        active = await self._active_version(session, deployment=deployment)

        context = await self._context(session, active=active)
        decision = lifecycle.can_rollback(active.version_status, context)
        if not decision.allowed:
            raise ConflictError(decision.code or "invalid_state")

        target = await rollback_target(session, active_number=active.version_number)
        if target is None:
            raise ConflictError("rollback_no_target")
        if target_version_id is not None and target_version_id != target.model_version_id:
            raise ConflictError("invalid_target")
        # ER-F-07: validate the target *first*. An artifact the store cannot see
        # is a rollback that would fail on load, and failing here leaves the
        # active version untouched instead of leaving desired state pointed at
        # bytes that are gone.
        self._require_artifact(store=store, version=target, tenant_id=tenant_id)

        await self._refuse_if_busy(session)
        revision = await self._open_revision(
            session,
            tenant_id=tenant_id,
            deployment=deployment,
            kind=RevisionKind.ROLLBACK,
            to_version_id=target.model_version_id,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason,
            now=now,
        )
        await self._deployments.set_desired(
            session,
            deployment=deployment,
            version_id=target.model_version_id,
            state=DeploymentState.ROLLING_BACK,
            now=now,
        )
        logger.info(
            "rollback_requested",
            extra={
                "deployment_id": str(deployment.deployment_id),
                "from_version_number": active.version_number,
                "to_version_number": target.version_number,
            },
        )
        return ActivationRequest(deployment=deployment, revision=revision, target=target)

    # ------------------------------------------------------------------ parts

    async def _version(self, session: AsyncSession, *, version_id: uuid.UUID) -> ModelVersion:
        """Gate 4: another tenant's version is a `404`, never a `403`."""
        version = await session.get(ModelVersion, version_id)
        if version is None:
            raise NotFoundError("not_found")
        return version

    async def _active_version(
        self, session: AsyncSession, *, deployment: ModelDeployment
    ) -> ModelVersion:
        if deployment.active_version_id is None:
            # Nothing is serving, so there is nothing to roll back *from*. The
            # console's own sentence for a rollback with no target is the
            # honest one here too.
            raise ConflictError("rollback_requires_target")
        return await self._version(session, version_id=deployment.active_version_id)

    async def _context(
        self, session: AsyncSession, *, active: ModelVersion
    ) -> lifecycle.VersionContext:
        has_retired = bool(
            await session.scalar(
                sa.select(sa.literal(1))
                .select_from(ModelVersion)
                .where(ModelVersion.status == ModelVersionStatus.RETIRED.value)
                .limit(1)
            )
        )
        return lifecycle.VersionContext(
            active_number=active.version_number, has_retired=has_retired
        )

    async def _refuse_if_busy(self, session: AsyncSession) -> None:
        """One activation at a time.

        Two in flight would race on load-before-swap: both would wait for their
        own version to become ready, and whichever settled second would swap in
        a version the first had already replaced. `409` rather than a queue,
        because the caller can see the in-flight one on `/service-status` and
        decide.
        """
        if await self._deployments.pending_revision(session) is not None:
            raise ConflictError("activation_in_progress")

    async def _open_revision(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        deployment: ModelDeployment,
        kind: RevisionKind,
        to_version_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        actor_type: AuditActor,
        reason: str | None,
        now: dt.datetime | None,
    ) -> DeploymentRevision:
        number = await self._deployments.next_revision_number(
            session, deployment_id=deployment.deployment_id
        )
        revision = DeploymentRevision(
            tenant_id=tenant_id,
            deployment_id=deployment.deployment_id,
            revision=number,
            kind=kind.value,
            from_version_id=deployment.active_version_id,
            to_version_id=to_version_id,
            requested_by=actor_id,
            requested_by_type=actor_type.value,
            reason=reason,
            started_at=now or dt.datetime.now(dt.UTC),
        )
        session.add(revision)
        await session.flush()
        return revision

    def _require_artifact(
        self, *, store: ArtifactStore | None, version: ModelVersion, tenant_id: uuid.UUID
    ) -> None:
        """The bytes are still there, or the rollback is refused now.

        A `None` store is not a pass. It means this process was constructed
        without one, and a rollback validated by a process that cannot see the
        artifact store has validated nothing — so the check is skipped only
        where the store is genuinely absent by configuration, and the log line
        says so rather than the absence being silent.
        """
        if store is None:
            logger.warning(
                "rollback_target_unverified",
                extra={"model_version_id": str(version.model_version_id)},
            )
            return
        from graphrec.ml.bundle import BUNDLE_NAME
        from graphrec.storage import keys

        key = keys.bundle_key(tenant_id, version.model_version_id, BUNDLE_NAME)
        if not store.exists(key):
            logger.error(
                "rollback_target_artifact_missing",
                extra={
                    "model_version_id": str(version.model_version_id),
                    "tenant_id": str(tenant_id),
                },
            )
            raise ConflictError("rollback_no_target")


__all__ = ["ActivationRequest", "ActivationService"]
