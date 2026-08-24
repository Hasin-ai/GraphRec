"""Roll every tenant's replicas onto a new image.

A deploy changes `GRAPHREC_IMAGE_TAG` and restarts the three Compose stacks. It
does not touch the inference containers, because they are not in any Compose
file a deploy restarts: there is one project per tenant and the reconciler owns
them all. Left alone, the estate ends a deploy with a new control plane and a
serving fleet still running last week's image, and nothing says so.

This is what closes that gap. It bumps the epoch on every live deployment
without changing `desired_version_id`, which is the difference between *this
tenant should serve a different model* and *this tenant should serve the same
model out of a different container*. The reconciler then sees replicas whose
`com.graphrec.epoch` label is behind and rolls them the way it rolls anything
else — load before swap, previous version retired only once the new replicas
report ready (ER-F-06).

**One tenant at a time, with a pause.** Bumping every epoch in one transaction
is one line shorter and asks the serving node to start a second full set of
replicas for every tenant at once. `--pause` is the crude version of a rolling
deploy and it is deliberately crude: the reconciler already refuses to retire a
working version, so the risk being managed here is memory on N3, not
correctness.

**It changes desired state and nothing else.** No containers are started here,
no Docker daemon is contacted, and the process exits without waiting. Watching
the roll is `docs/RUNBOOKS.md#force-a-rollback`'s job and Grafana's; a
deploy step that blocked until every tenant converged would hold a CI job open
for as long as the slowest bundle takes to download.

Usage:
    python -m apps.reconciler.roll --image <tag> [--pause 10] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.common.config import get_settings
from graphrec.common.enums import DeploymentState, TenantStatus
from graphrec.common.logging import configure_logging, get_logger
from graphrec.db.engine import create_platform_engine, create_sessionmaker, create_worker_engine
from graphrec.db.models import ModelDeployment, Tenant
from graphrec.db.tenant_context import bind_tenant
from graphrec.domain.serving.deployment import DeploymentService

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        required=True,
        help="The tag being rolled to. Recorded in the log, not read: the image "
        "the replicas start with comes from the reconciler's own environment, "
        "and this is here so the log line says which deploy caused the roll.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=10.0,
        help="Seconds between tenants. The reconciler's pass interval is the "
        "floor worth using; anything shorter just queues.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be rolled and change nothing.",
    )
    return parser.parse_args(argv)


async def _live_tenants(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[tuple[uuid.UUID, str]]:
    """Active tenants with a deployment that is meant to be serving.

    Read as the platform role, which holds six columns of `model_deployments`
    and no more — enough to learn that a tenant has something to roll and not
    enough to learn what it is serving.

    Stopped deployments are skipped rather than rolled. A halted deployment
    remembers its version so a resumed tenant comes back on it, and bumping its
    epoch would make every replica permanently drifted from a deployment that is
    not changing — the same reason `halt` is idempotent.
    """
    async with sessionmaker() as session:
        rows = await session.execute(
            sa.select(ModelDeployment.tenant_id, ModelDeployment.state)
            .join(Tenant, Tenant.tenant_id == ModelDeployment.tenant_id)
            .where(
                Tenant.status == TenantStatus.ACTIVE.value,
                ModelDeployment.desired_replicas > 0,
                ModelDeployment.state != DeploymentState.STOPPED.value,
            )
            .order_by(ModelDeployment.tenant_id)
        )
        return [(row.tenant_id, row.state) for row in rows.all()]


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    platform_engine = create_platform_engine(settings)
    worker_engine = create_worker_engine(settings)
    platform_sessions = create_sessionmaker(platform_engine)
    tenant_sessions = create_sessionmaker(worker_engine)
    deployments = DeploymentService()

    try:
        targets = await _live_tenants(platform_sessions)
        logger.info(
            "roll_starting",
            extra={"image": args.image, "tenants": len(targets), "dry_run": args.dry_run},
        )
        if not targets:
            print("nothing to roll: no active tenant has a running deployment")
            return 0

        rolled = 0
        for index, (tenant_id, state) in enumerate(targets):
            if args.dry_run:
                print(f"would roll {tenant_id} (state={state})")
                continue

            async with tenant_sessions() as session, session.begin():
                await bind_tenant(session, tenant_id)
                deployment = await deployments.find(session)
                if deployment is None:
                    # Deleted between the sweep and now, exactly as the
                    # reconciler's own pass handles it.
                    continue
                # The same version, deliberately. `set_desired` is the audited
                # path that bumps the epoch and leaves `active_version_id`
                # alone, and re-implementing the bump here would be a second
                # place for ER-F-06's invariant to be got wrong.
                if deployment.desired_version_id is None:
                    # A deployment that has never been activated has no version
                    # to roll onto. It is not an error and it is not silent.
                    print(f"skipped {tenant_id}: no desired version")
                    continue
                await deployments.set_desired(
                    session,
                    deployment=deployment,
                    version_id=deployment.desired_version_id,
                    replicas=deployment.desired_replicas,
                )
            rolled += 1
            print(f"rolled {tenant_id} (state={state})")

            if args.pause and index + 1 < len(targets):
                await asyncio.sleep(args.pause)

        logger.info("roll_finished", extra={"image": args.image, "rolled": rolled})
        print(f"requested a roll for {rolled} tenant(s) onto {args.image}")
        return 0
    finally:
        await worker_engine.dispose()
        await platform_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
