"""`apps.reconciler.roll` — the step that puts the serving fleet on a new image.

The gap this closes is a quiet one. A deploy restarts three Compose stacks and
none of them contains an inference container: there is one project per tenant
and the reconciler owns them all. So a deploy that changed the image tag ends
with a new control plane and a serving fleet still on the previous image, with
nothing anywhere saying so.

What is asserted here is the selection, not the mechanism. Which deployments get
an epoch bump is the whole of the decision — the bump itself goes through
`set_desired`, which is already covered, and the roll is exactly the reconciler's
ordinary convergence once desired state has moved.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.reconciler.roll import _live_tenants, parse_args
from graphrec.common.enums import DeploymentState, TenantStatus
from graphrec.db.models import ModelDeployment

pytestmark = [pytest.mark.db]


def _platform_url() -> str:
    owner = os.environ.get(
        "GRAPHREC_OWNER_DATABASE_URL",
        "postgresql+psycopg://graphrec_owner:graphrec_owner_local_only@localhost:5432/graphrec",
    )
    tail = owner.split("@", 1)[1]
    password = os.environ.get("POSTGRES_PLATFORM_PASSWORD", "graphrec_platform_local_only")
    return f"postgresql+psycopg://graphrec_platform:{password}@{tail}"


@pytest.fixture
async def platform_sessionmaker():
    """Sessions as `graphrec_platform`, which is the role `_live_tenants` runs as.

    Not the app role, and the difference is the whole test. Under `FORCE ROW
    LEVEL SECURITY` a tenant-role session with no tenant bound reads nothing, so
    a selection test written against it would pass by seeing an empty result
    whatever the query said. The platform role holds a cross-tenant `SELECT` on
    six columns of `model_deployments` (migration 0012) and that is what the
    sweep depends on.
    """
    engine = create_async_engine(_platform_url(), poolclass=sa.pool.NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


async def _seed_deployment(
    sessionmaker,
    tenant_id: uuid.UUID,
    *,
    state: DeploymentState,
    desired_replicas: int,
) -> None:
    async with sessionmaker() as session, session.begin():
        await session.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        # `model_id` is NOT NULL, so a deployment needs a model even when the
        # test is only about which deployments get selected.
        model_id = uuid.uuid4()
        await session.execute(
            sa.text(
                "INSERT INTO models (model_id, tenant_id, name, model_type) "
                "VALUES (:mid, :tid, 'roll', 'DGSR')"
            ),
            {"mid": model_id, "tid": tenant_id},
        )
        session.add(
            ModelDeployment(
                tenant_id=tenant_id,
                model_id=model_id,
                state=state.value,
                desired_replicas=desired_replicas,
                ready_replicas=0,
            )
        )


# ------------------------------------------------------------------ arguments


def test_the_image_tag_is_required() -> None:
    """It is recorded in the log line and nowhere else, and it is still
    required: a roll with no record of which deploy caused it is a fleet
    restart nobody can attribute afterwards."""
    with pytest.raises(SystemExit):
        parse_args([])


def test_the_pause_defaults_to_the_reconcilers_own_interval() -> None:
    """Rolling every tenant at once asks N3 to hold two full sets of replicas.
    The default is a floor, not a tuning knob."""
    args = parse_args(["--image", "abc123"])
    assert args.pause >= 10.0
    assert args.dry_run is False


# ------------------------------------------------------------------ selection


async def test_a_stopped_deployment_is_not_rolled(
    serving_sessionmaker, platform_sessionmaker, serving_tenants
) -> None:
    """A halted deployment remembers the version it was serving so a resumed
    tenant comes back on it. Bumping its epoch would leave every replica
    permanently drifted from a deployment that is not changing — the same
    reason `halt` is idempotent."""
    await _seed_deployment(
        serving_sessionmaker,
        serving_tenants["alpha"],
        state=DeploymentState.STOPPED,
        desired_replicas=0,
    )
    await _seed_deployment(
        serving_sessionmaker,
        serving_tenants["beta"],
        state=DeploymentState.PROGRESSING,
        desired_replicas=2,
    )

    selected = {tenant_id for tenant_id, _ in await _live_tenants(platform_sessionmaker)}
    assert selected == {serving_tenants["beta"]}


async def test_a_suspended_tenant_is_not_rolled(
    serving_sessionmaker, platform_sessionmaker, serving_tenants, seed_engine_sync
) -> None:
    """Suspension already winds desired capacity to nothing. Rolling one would
    be asking the serving node to start containers for a tenant the platform
    has decided must not be served."""
    await _seed_deployment(
        serving_sessionmaker,
        serving_tenants["alpha"],
        state=DeploymentState.PROGRESSING,
        desired_replicas=2,
    )
    # Through the owner with the tenant bound, the way `serving_tenants` seeds.
    # A tenant-role session with nothing bound updates zero rows and says so by
    # returning, which would leave this test asserting on a suspension that
    # never happened.
    with seed_engine_sync.begin() as conn:
        conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(serving_tenants["alpha"])},
        )
        updated = conn.execute(
            sa.text("UPDATE tenants SET status = :s WHERE tenant_id = :t"),
            {"s": TenantStatus.SUSPENDED.value, "t": serving_tenants["alpha"]},
        )
        assert updated.rowcount == 1

    assert await _live_tenants(platform_sessionmaker) == []


async def test_nothing_to_roll_is_not_a_failure(platform_sessionmaker, serving_tenants) -> None:
    """A fresh estate has no deployments. A deploy step that failed on that
    would make the first deploy of a new environment red for the one reason
    that is not a problem."""
    assert await _live_tenants(platform_sessionmaker) == []
