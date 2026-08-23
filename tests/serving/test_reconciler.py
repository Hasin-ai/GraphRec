"""The convergence loop, its leader lock, and the floor it maintains.

Three things are asserted, and only one of them is about deployments:

* **One leader.** `pg_try_advisory_lock` is held by a *session*, so a second
  reconciler must be refused and a dead one must release without anybody
  noticing it died. Both are tested against a real second connection, because
  the property is PostgreSQL's and a mock would be testing the mock.
* **`ready >= 1` (NR-NF-08).** Reported rather than raised: the pass that starts
  the first replica necessarily observes zero. So what is asserted is that the
  breach is *transient* — it appears while a deployment is coming up and is gone
  once it has, and it never appears for a deployment that is already serving.
* **A sweep is per tenant.** One unreachable orchestrator strands one tenant's
  activation, not everybody's.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from graphrec.common.enums import DeploymentState, ModelVersionStatus
from graphrec.db.models import ModelDeployment, ModelVersion
from graphrec.domain.serving.activation import ActivationService
from graphrec.domain.serving.reconciler import (
    acquire_leadership,
    converge,
    release_leadership,
)
from graphrec.serving.states import ReplicaStatus
from graphrec.serving_driver import InProcessDriver
from graphrec.serving_driver.driver import DriverError
from tests.serving.conftest import NOW

pytestmark = [pytest.mark.db]

ACTOR = uuid.uuid4()


async def _deployment(session) -> ModelDeployment:
    found = await session.scalar(sa.select(ModelDeployment))
    assert found is not None
    return found


# ------------------------------------------------------------------ election


async def test_only_one_reconciler_holds_the_lock(serving_sessionmaker) -> None:
    """Two converging one tenant would fight over the replica count.

    The loser's `up --scale` would undo the winner's, which is a deployment that
    oscillates rather than one that fails — the harder of the two to diagnose.
    """
    async with serving_sessionmaker() as leader, serving_sessionmaker() as follower:
        assert await acquire_leadership(leader) is True
        assert (
            await acquire_leadership(follower) is False
        ), "a second reconciler must return immediately, not wait"
        await release_leadership(leader)
        # And the lock is genuinely free afterwards, rather than held until the
        # process exits.
        assert await acquire_leadership(follower) is True
        await release_leadership(follower)


async def test_the_lock_is_released_when_the_session_goes(serving_sessionmaker) -> None:
    """This is why it is a session advisory lock and not a lease row.

    A reconciler killed mid-pass releases without anyone having to observe that
    it died. A lease in a table would need a sweeper, and the sweeper would need
    a timeout, and the timeout would be the length of every failover.
    """
    async with serving_sessionmaker() as first:
        assert await acquire_leadership(first) is True

    async with serving_sessionmaker() as second:
        assert await acquire_leadership(second) is True
        await release_leadership(second)


# --------------------------------------------------------------------- floor


async def test_the_floor_is_breached_while_coming_up_and_restored_once_ready(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """NR-NF-08 as the loop actually maintains it.

    Zero ready is legitimate for exactly as long as it takes a container to
    load. What is not legitimate is staying there, and `floor_breached` is the
    number a monitor watches across passes.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id)
    driver = InProcessDriver()

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session, tenant_id=tenant_id, version_id=version_id, actor_id=ACTOR, now=NOW
        )

    async with bound_serving(tenant_id) as session:
        starting = await converge(
            session, driver=driver, deployment=await _deployment(session), now=NOW
        )
    assert starting.floor_breached is True, "nothing has loaded yet, and that is honest"

    driver.settle(tenant_id)
    async with bound_serving(tenant_id) as session:
        ready = await converge(
            session, driver=driver, deployment=await _deployment(session), now=NOW
        )

    assert ready.swapped is True
    assert ready.ready_replicas >= 1

    # And a steady-state pass over a serving deployment never reports a breach.
    async with bound_serving(tenant_id) as session:
        steady = await converge(
            session, driver=driver, deployment=await _deployment(session), now=NOW
        )
    assert steady.floor_breached is False
    assert steady.state is DeploymentState.AVAILABLE


async def test_every_replica_the_driver_reports_becomes_a_row(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """`serving_replicas` is what `/deployment/replicas` renders.

    Written before the swap decision, so a crash between the two leaves
    `/service-status` honest rather than showing a deployment with no replicas.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id, desired_replicas=3, min_replicas=3)
    driver = InProcessDriver()

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session, tenant_id=tenant_id, version_id=version_id, actor_id=ACTOR, now=NOW
        )
    async with bound_serving(tenant_id) as session:
        await converge(session, driver=driver, deployment=await _deployment(session), now=NOW)

    async with bound_serving(tenant_id) as session:
        rows = (
            await session.execute(
                sa.text("SELECT status, ready FROM serving_replicas ORDER BY replica_ref")
            )
        ).all()

    assert len(rows) == 3
    assert {row[0] for row in rows} == {ReplicaStatus.STARTING.value}
    assert not any(row[1] for row in rows)


async def test_a_deployment_that_loses_every_replica_is_degraded_not_swapped_away(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """A tenant whose containers died still has an active version.

    `degraded` says "this should be serving and is not", which is a different
    sentence from "this tenant has no model" — and the console needs to be able
    to tell a customer which of the two happened.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id)
    driver = InProcessDriver()

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session, tenant_id=tenant_id, version_id=version_id, actor_id=ACTOR, now=NOW
        )
    async with bound_serving(tenant_id) as session:
        await converge(session, driver=driver, deployment=await _deployment(session), now=NOW)
    driver.settle(tenant_id)
    async with bound_serving(tenant_id) as session:
        await converge(session, driver=driver, deployment=await _deployment(session), now=NOW)

    driver.fail(tenant_id)
    async with bound_serving(tenant_id) as session:
        after = await converge(
            session, driver=driver, deployment=await _deployment(session), now=NOW
        )

    assert after.floor_breached is True
    async with bound_serving(tenant_id) as session:
        deployment = await _deployment(session)
        assert deployment.active_version_id == version_id
        version = await session.get(ModelVersion, version_id)
        assert version is not None
        assert version.status == ModelVersionStatus.ACTIVE.value


async def test_an_unreachable_orchestrator_does_not_fail_the_activation(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """A transient Docker socket must not spend a tenant's version.

    `failed_deployment` means "this model would not load". Marking a version
    with it because a daemon was restarting would send a tenant off to retrain a
    model that was fine.
    """

    class Unreachable:
        async def apply(self, desired):
            msg = "docker compose up failed: cannot connect to the daemon"
            raise DriverError(msg)

        async def observe(self, tenant_id):
            msg = "docker compose ps failed: cannot connect to the daemon"
            raise DriverError(msg)

        async def stop(self, tenant_id):
            raise DriverError("no")

        def describe(self):
            from graphrec.serving_driver.driver import DriverInfo

            return DriverInfo(
                kind="unreachable", supports_multi_node=False, max_replicas_per_tenant=1
            )

    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id)

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session, tenant_id=tenant_id, version_id=version_id, actor_id=ACTOR, now=NOW
        )
    async with bound_serving(tenant_id) as session:
        result = await converge(
            session, driver=Unreachable(), deployment=await _deployment(session), now=NOW
        )

    assert result.failed is False
    assert result.detail is not None
    async with bound_serving(tenant_id) as session:
        version = await session.get(ModelVersion, version_id)
        assert version is not None
        assert version.status == ModelVersionStatus.ELIGIBLE.value


async def test_one_tenants_failure_does_not_strand_another(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """The sweep is per tenant, and so is the `except`.

    Alpha's orchestrator is unreachable; beta's is not. Beta converges anyway,
    which is the whole reason the loop catches per tenant rather than per pass.
    """
    alpha, beta = serving_tenants["alpha"], serving_tenants["beta"]
    for tenant_id in (alpha, beta):
        seed_catalogue(tenant_id)
    alpha_version = seed_model_version(alpha, version_number=1)
    beta_version = seed_model_version(beta, version_number=1)
    seed_deployment(alpha)
    seed_deployment(beta)

    driver = InProcessDriver()
    for tenant_id, version_id in ((alpha, alpha_version), (beta, beta_version)):
        async with bound_serving(tenant_id) as session:
            await ActivationService().activate(
                session, tenant_id=tenant_id, version_id=version_id, actor_id=ACTOR, now=NOW
            )

    class OnlyBeta:
        async def apply(self, desired):
            if desired.tenant_id == alpha:
                msg = "docker compose up failed"
                raise DriverError(msg)
            return await driver.apply(desired)

        async def observe(self, tenant_id):
            return await driver.observe(tenant_id)

        async def stop(self, tenant_id):
            return await driver.stop(tenant_id)

        def describe(self):
            return driver.describe()

    partial = OnlyBeta()
    for tenant_id in (alpha, beta):
        async with bound_serving(tenant_id) as session:
            await converge(session, driver=partial, deployment=await _deployment(session), now=NOW)
    driver.settle(beta)
    async with bound_serving(beta) as session:
        settled = await converge(
            session, driver=partial, deployment=await _deployment(session), now=NOW
        )

    assert settled.swapped is True


async def test_a_suspended_tenant_is_wound_down_and_its_containers_stopped(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """Suspension has to reach the containers, not just the console.

    The platform role deliberately holds no write on `model_deployments`, so
    suspending a tenant cannot itself stop their serving — the API changes
    `tenants.status` and nothing else. The reconciler is what closes the gap: it
    reads the status on its sweep and converges a suspended tenant towards zero.

    Asserted at the driver rather than only at the row, because a deployment
    marked `stopped` while its containers keep answering is the failure this
    exists to prevent — and it is a failure that looks fine in the console.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id)
    driver = InProcessDriver()

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session, tenant_id=tenant_id, version_id=version_id, actor_id=ACTOR, now=NOW
        )
    async with bound_serving(tenant_id) as session:
        await converge(session, driver=driver, deployment=await _deployment(session), now=NOW)
    driver.settle(tenant_id)
    async with bound_serving(tenant_id) as session:
        running = await converge(
            session, driver=driver, deployment=await _deployment(session), now=NOW
        )
    assert running.ready_replicas >= 1

    async with bound_serving(tenant_id) as session:
        stopped = await converge(
            session,
            driver=driver,
            deployment=await _deployment(session),
            now=NOW,
            suspended=True,
        )

    assert stopped.state is DeploymentState.STOPPED
    assert stopped.ready_replicas == 0
    assert not (await driver.observe(tenant_id)).replicas, "the containers are still up"

    # And the pass is idempotent: the sweep comes back every few seconds, and a
    # suspended tenant must not accumulate an epoch bump per pass.
    async with bound_serving(tenant_id) as session:
        deployment = await _deployment(session)
        epoch = deployment.epoch
        again = await converge(
            session, driver=driver, deployment=deployment, now=NOW, suspended=True
        )
    assert again.state is DeploymentState.STOPPED
    assert deployment.epoch == epoch


async def test_restoring_a_tenant_brings_serving_back(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """Reactivation is not a second activation: the tenant's active version is
    still there, so the reconciler restores desired capacity to the floor rather
    than waiting for someone to promote a model again."""
    tenant_id = serving_tenants["beta"]
    seed_catalogue(tenant_id)
    version_id = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id)
    driver = InProcessDriver()

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session, tenant_id=tenant_id, version_id=version_id, actor_id=ACTOR, now=NOW
        )
    async with bound_serving(tenant_id) as session:
        await converge(session, driver=driver, deployment=await _deployment(session), now=NOW)
    driver.settle(tenant_id)
    async with bound_serving(tenant_id) as session:
        await converge(session, driver=driver, deployment=await _deployment(session), now=NOW)
    async with bound_serving(tenant_id) as session:
        await converge(
            session,
            driver=driver,
            deployment=await _deployment(session),
            now=NOW,
            suspended=True,
        )

    async with bound_serving(tenant_id) as session:
        resumed = await converge(
            session, driver=driver, deployment=await _deployment(session), now=NOW
        )
    assert resumed.state is not DeploymentState.STOPPED
    assert resumed.desired_replicas >= 1
