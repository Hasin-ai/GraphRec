"""Load before swap, and roll back to a version that is still there.

ER-F-06 and ER-F-07 are one requirement seen from two ends: the previous version
must survive an activation that fails, *because* it is the thing a rollback
returns to. So both are asserted here, against real rows and a driver with real
behaviour, rather than against a stub whose `observe` says whatever the test
needs.

The sequence under test is always the same three beats, because that is the
sequence the requirement is about:

    activate  →  desired moves, active does not
    converge  →  containers start, nothing is ready, active still does not move
    settle    →  a replica answers with the new version, and only then it moves
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa

from graphrec.common.enums import DeploymentState, ModelVersionStatus
from graphrec.common.errors import ConflictError, NotFoundError
from graphrec.db.models import ModelDeployment, ModelVersion
from graphrec.domain.serving.activation import ActivationService
from graphrec.domain.serving.reconciler import converge
from graphrec.serving.states import RevisionStatus
from graphrec.serving_driver import InProcessDriver
from tests.serving.conftest import NOW

pytestmark = [pytest.mark.db]

ACTOR = uuid.uuid4()
#: Shorter than the pass count below, so "the activation ran out of time" is an
#: event this suite can produce without waiting ten minutes for it.
TIMEOUT = dt.timedelta(minutes=10)


async def _deployment(session) -> ModelDeployment:
    found = await session.scalar(sa.select(ModelDeployment))
    assert found is not None
    return found


async def _status(session, version_id: uuid.UUID) -> str:
    version = await session.get(ModelVersion, version_id)
    assert version is not None
    return str(version.status)


async def test_activation_moves_desired_and_leaves_active_alone(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """The first beat. `:activate` records an intention and nothing else.

    If it moved `active_version_id` here and then started containers, a bundle
    that would not load would leave the tenant with an active version nothing is
    serving — precisely the failure ER-F-06 names.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    previous = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    candidate = seed_model_version(tenant_id, version_number=2)
    seed_deployment(tenant_id, active_version_id=previous, desired_version_id=previous)

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session, tenant_id=tenant_id, version_id=candidate, actor_id=ACTOR, now=NOW
        )

    async with bound_serving(tenant_id) as session:
        deployment = await _deployment(session)
        assert deployment.desired_version_id == candidate
        assert deployment.active_version_id == previous
        assert deployment.deployment_state is DeploymentState.PROGRESSING
        # And the previous version is still the one marked active, which is what
        # `/v1/recommendations` reads when no process is pinned.
        assert await _status(session, previous) == ModelVersionStatus.ACTIVE.value
        assert await _status(session, candidate) == ModelVersionStatus.ELIGIBLE.value


async def test_a_failed_activation_leaves_the_previous_version_serving(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """ER-F-06, stated as an outcome rather than as a mechanism.

    The driver starts nothing — the shape of a host that is full, an image that
    will not pull, or a bundle that will not load. The activation times out, the
    candidate is marked `failed_deployment`, and the tenant's previous version is
    exactly where it was: `active`, and pointed at by the deployment.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    previous = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    candidate = seed_model_version(tenant_id, version_number=2)
    seed_deployment(tenant_id, active_version_id=previous, desired_version_id=previous)

    driver = InProcessDriver()
    driver.refuse_to_start = True

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session, tenant_id=tenant_id, version_id=candidate, actor_id=ACTOR, now=NOW
        )

    # One pass now, and one after the deadline. The first must not fail it —
    # a deployment is allowed to be slow — and the second must.
    async with bound_serving(tenant_id) as session:
        early = await converge(
            session, driver=driver, deployment=await _deployment(session), now=NOW
        )
    assert early.failed is False
    assert early.swapped is False

    async with bound_serving(tenant_id) as session:
        late = await converge(
            session,
            driver=driver,
            deployment=await _deployment(session),
            activation_timeout=TIMEOUT,
            now=NOW + TIMEOUT + dt.timedelta(minutes=1),
        )

    assert late.failed is True
    async with bound_serving(tenant_id) as session:
        deployment = await _deployment(session)
        assert deployment.active_version_id == previous
        assert (
            deployment.desired_version_id == previous
        ), "desired must be walked back to the version that is actually serving"
        assert await _status(session, previous) == ModelVersionStatus.ACTIVE.value
        assert await _status(session, candidate) == ModelVersionStatus.FAILED_DEPLOYMENT.value


async def test_the_swap_waits_for_a_replica_answering_with_the_new_version(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """Not "the driver accepted the apply" and not "a container exists".

    The count that moves `active_version_id` is `observation.serving(desired)`,
    and this test walks the three states it passes through so a regression that
    swapped on `live_count` would fail on the middle one.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    previous = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    candidate = seed_model_version(tenant_id, version_number=2)
    seed_deployment(tenant_id, active_version_id=previous, desired_version_id=previous)
    driver = InProcessDriver()

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session, tenant_id=tenant_id, version_id=candidate, actor_id=ACTOR, now=NOW
        )

    async with bound_serving(tenant_id) as session:
        starting = await converge(
            session, driver=driver, deployment=await _deployment(session), now=NOW
        )
    assert starting.swapped is False, "a container that exists has not loaded a bundle"

    driver.settle(tenant_id)

    async with bound_serving(tenant_id) as session:
        swapped = await converge(
            session,
            driver=driver,
            deployment=await _deployment(session),
            now=NOW + dt.timedelta(minutes=1),
        )

    assert swapped.swapped is True
    async with bound_serving(tenant_id) as session:
        deployment = await _deployment(session)
        assert deployment.active_version_id == candidate
        assert deployment.deployment_state is DeploymentState.AVAILABLE
        assert await _status(session, candidate) == ModelVersionStatus.ACTIVE.value
        # Retired, not archived. This is the row ER-F-07 rolls back to, and an
        # archived version has had its artifact deleted.
        assert await _status(session, previous) == ModelVersionStatus.RETIRED.value


async def test_a_successful_swap_settles_its_revision_and_records_the_actor(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """ "Who activated version 2" must not resolve to the reconciler.

    The actor travels on the revision, written by the request, and is copied
    into `model_activation_history` at swap time — minutes later, in another
    process, with no user in sight.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    candidate = seed_model_version(tenant_id, version_number=1)
    seed_deployment(tenant_id)
    driver = InProcessDriver()

    async with bound_serving(tenant_id) as session:
        await ActivationService().activate(
            session,
            tenant_id=tenant_id,
            version_id=candidate,
            actor_id=ACTOR,
            reason="Recall improved by four points.",
            now=NOW,
        )
    async with bound_serving(tenant_id) as session:
        await converge(session, driver=driver, deployment=await _deployment(session), now=NOW)
    driver.settle(tenant_id)
    async with bound_serving(tenant_id) as session:
        await converge(session, driver=driver, deployment=await _deployment(session), now=NOW)

    async with bound_serving(tenant_id) as session:
        revision_status, revision_actor = (
            await session.execute(
                sa.text("SELECT status, requested_by FROM deployment_revisions LIMIT 1")
            )
        ).one()
        history_actor, history_reason, to_version = (
            await session.execute(
                sa.text(
                    "SELECT actor_id, reason, to_version_id FROM model_activation_history LIMIT 1"
                )
            )
        ).one()

    assert revision_status == RevisionStatus.SUCCEEDED.value
    assert revision_actor == ACTOR
    assert history_actor == ACTOR
    assert history_reason == "Recall improved by four points."
    assert to_version == candidate


# ------------------------------------------------------------------- rollback


async def test_rollback_refuses_a_target_that_is_not_the_retained_one(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """The body's `target_version_id` confirms; it does not select.

    A dialog that has been open while v7 was archived would otherwise silently
    roll back to v6 — the same button, a different outcome, and no way for the
    person pressing it to know.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    oldest = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.RETIRED)
    previous = seed_model_version(tenant_id, version_number=2, status=ModelVersionStatus.RETIRED)
    active = seed_model_version(tenant_id, version_number=3, status=ModelVersionStatus.ACTIVE)
    seed_deployment(tenant_id, active_version_id=active, desired_version_id=active)

    async with bound_serving(tenant_id) as session:
        with pytest.raises(ConflictError) as raised:
            await ActivationService().rollback(
                session,
                tenant_id=tenant_id,
                actor_id=ACTOR,
                target_version_id=oldest,
                reason="Rolling back after a bad release.",
                now=NOW,
            )

    assert raised.value.code == "invalid_target"
    # And confirming the *right* one is accepted, so the refusal above is about
    # the target rather than about rollback being broken.
    async with bound_serving(tenant_id) as session:
        request = await ActivationService().rollback(
            session,
            tenant_id=tenant_id,
            actor_id=ACTOR,
            target_version_id=previous,
            reason="Rolling back after a bad release.",
            now=NOW,
        )
    assert request.target.model_version_id == previous


async def test_rollback_validates_before_it_changes_anything(
    serving_tenants, seed_catalogue, seed_model_version, seed_deployment, bound_serving
) -> None:
    """ER-F-07. A refused rollback leaves desired state untouched.

    Checking after the desired state moved would point the deployment at a
    version it cannot serve, and the next convergence pass would spend the
    activation timeout discovering it.
    """
    tenant_id = serving_tenants["alpha"]
    seed_catalogue(tenant_id)
    active = seed_model_version(tenant_id, version_number=1, status=ModelVersionStatus.ACTIVE)
    seed_deployment(tenant_id, active_version_id=active, desired_version_id=active)

    async with bound_serving(tenant_id) as session:
        with pytest.raises((ConflictError, NotFoundError)):
            # There is no previous version at all — the first activation a
            # tenant ever performs has nothing behind it.
            await ActivationService().rollback(
                session,
                tenant_id=tenant_id,
                actor_id=ACTOR,
                reason="Nothing to go back to.",
                now=NOW,
            )

    async with bound_serving(tenant_id) as session:
        deployment = await _deployment(session)
        assert deployment.desired_version_id == active
        assert deployment.active_version_id == active
        assert await session.scalar(sa.text("SELECT count(*) FROM deployment_revisions")) == 0
