"""The `ServingDriver` port, and the two things that implement it.

The point of a port with two adapters is that the code above it cannot tell
them apart. So the contract is stated once and parametrised over both, and where
`ComposeDriver` cannot participate — it needs a Docker daemon — the test says so
by skipping rather than by quietly testing only the in-process one.

`_parse_ps` gets its own tests with fixed fixtures rather than a live daemon,
because the mapping from Compose's output to `ReplicaObservation` is the whole
of what the adapter does and it is the part most likely to break under a Docker
upgrade. Those fixtures are the real shapes Compose has emitted across versions.
"""

from __future__ import annotations

import shutil
import uuid

import pytest

from graphrec.common.config import ServingDriverKind
from graphrec.serving.states import ReplicaStatus
from graphrec.serving_driver import (
    ComposeDriver,
    DesiredState,
    InProcessDriver,
    ServingDriver,
    build_serving_driver,
    project_name,
)
from graphrec.serving_driver.compose import _parse_ps

TENANT = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
VERSION = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")

_docker = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="serving_driver=compose needs a Docker daemon; the port's contract is "
    "asserted against InProcessDriver and the parsing against fixtures",
)


def _drivers() -> list[ServingDriver]:
    return [
        InProcessDriver(),
        ComposeDriver(compose_file="deploy/single/docker-compose.serving.yml"),
    ]


@pytest.mark.parametrize("driver", _drivers(), ids=["inprocess", "compose"])
def test_every_driver_describes_its_own_limits(driver: ServingDriver) -> None:
    """`DriverInfo` is how ADR 0028's admitted limit stays visible.

    Compose cannot spread replicas across nodes. That is reported rather than
    hidden, so `/deployment/autoscaling` can say why the ceiling is where it is
    instead of presenting it as a policy someone chose.
    """
    info = driver.describe()

    assert info.kind in {"inprocess", "compose"}
    assert info.supports_multi_node is False
    assert info.max_replicas_per_tenant >= 1


def test_the_selector_refuses_k3s_by_name() -> None:
    """A deferred adapter that silently became the shipped one would be a
    deferral nobody found out about until the demonstration it was deferred for."""
    with pytest.raises(NotImplementedError) as raised:
        build_serving_driver(ServingDriverKind.K3S, compose_file="whatever.yml")

    assert "ADR 0028" in str(raised.value)


async def test_a_started_replica_is_not_ready_until_it_has_loaded() -> None:
    """The gap between `apply` and `ready` is where load-before-swap lives.

    A driver whose `apply` returned ready replicas would make ER-F-06
    untestable, because the window the requirement is about would not exist.
    """
    driver = InProcessDriver()

    observation = await driver.apply(
        DesiredState(tenant_id=TENANT, version_id=VERSION, bundle_uri="s3://b", replicas=2, epoch=1)
    )

    assert observation.live_count == 2
    assert observation.ready_count == 0
    assert observation.serving(VERSION) == 0

    driver.settle(TENANT)
    settled = await driver.observe(TENANT)

    assert settled.ready_count == 2
    assert settled.serving(VERSION) == 2


async def test_applying_a_new_version_replaces_the_old_replicas() -> None:
    """Desired state, not accumulation.

    A leftover replica answering with the previous version is exactly the drift
    the epoch exists to catch, and a driver that kept them would report
    `serving(old) == 2` forever.
    """
    driver = InProcessDriver()
    older = uuid.uuid4()
    await driver.apply(
        DesiredState(tenant_id=TENANT, version_id=older, bundle_uri="s3://b", replicas=1, epoch=1)
    )
    driver.settle(TENANT)

    await driver.apply(
        DesiredState(tenant_id=TENANT, version_id=VERSION, bundle_uri="s3://b", replicas=1, epoch=2)
    )
    observation = await driver.observe(TENANT)

    assert observation.serving(older) == 0
    assert observation.live_count == 1


async def test_stop_removes_every_replica_and_says_so() -> None:
    driver = InProcessDriver()
    await driver.apply(
        DesiredState(tenant_id=TENANT, version_id=VERSION, bundle_uri="s3://b", replicas=3, epoch=1)
    )

    observation = await driver.stop(TENANT)

    assert observation.live_count == 0
    assert observation.ready_count == 0


async def test_two_tenants_never_see_each_others_replicas() -> None:
    """The project name is the boundary, and it is derived from the tenant id.

    `observe` takes a tenant and can only be asked about one, which is the same
    shape the Compose adapter has: `--project-name graphrec-serve-<tenant>`.
    """
    driver = InProcessDriver()
    other = uuid.uuid4()
    await driver.apply(
        DesiredState(tenant_id=TENANT, version_id=VERSION, bundle_uri="s3://b", replicas=2, epoch=1)
    )

    assert (await driver.observe(other)).live_count == 0
    assert project_name(TENANT) != project_name(other)


# ----------------------------------------------------------------- ps parsing


def test_compose_ps_is_read_as_json_lines() -> None:
    """The shape recent Docker emits."""
    raw = (
        '{"Name":"graphrec-serve-a-inference-1","State":"running","Health":"healthy",'
        '"Status":"Up 2 minutes (healthy)",'
        '"Labels":"com.graphrec.version=bbbbbbbb-0000-0000-0000-000000000001,'
        'com.graphrec.epoch=4"}\n'
    )

    [replica] = _parse_ps(raw)

    assert replica.status is ReplicaStatus.RUNNING
    assert replica.ready is True
    assert replica.version_id == VERSION
    assert replica.epoch == 4


def test_compose_ps_is_also_read_as_a_json_array() -> None:
    """Older Docker emitted an array. Both are accepted because both exist in
    the field, and a driver that only handled one would break on upgrade."""
    raw = (
        '[{"Name":"x-inference-1","State":"running","Health":"healthy","Labels":{}},'
        '{"Name":"x-inference-2","State":"exited","Health":"","Labels":{}}]'
    )

    replicas = _parse_ps(raw)

    assert [r.status for r in replicas] == [ReplicaStatus.RUNNING, ReplicaStatus.STOPPED]
    assert [r.ready for r in replicas] == [True, False]


def test_a_running_container_that_is_unhealthy_is_not_ready() -> None:
    """This is the healthcheck in `docker-compose.serving.yml` doing its job.

    `/readyz` answers `ready: false` until a verified bundle is resident, the
    container stays unhealthy, and `serving(desired)` stays at zero — so the
    reconciler does not swap. A driver that read `State` alone would report a
    replica that never loaded a bundle as ready.
    """
    raw = (
        '{"Name":"x-inference-1","State":"running","Health":"starting",'
        '"Status":"Up 8 seconds (health: starting)","Labels":""}'
    )

    [replica] = _parse_ps(raw)

    assert replica.status is ReplicaStatus.RUNNING
    assert replica.ready is False


def test_one_unreadable_line_costs_one_replica_and_not_the_observation() -> None:
    """The reconciler treats a missing replica as one to start, which is the
    safe direction. Raising would make the whole pass fail on one bad line."""
    raw = '{"Name":"x-inference-1","State":"running","Health":"healthy"}\nnot json at all\n'

    replicas = _parse_ps(raw)

    assert len(replicas) == 1


def test_an_empty_ps_is_no_replicas_rather_than_an_error() -> None:
    assert _parse_ps("") == []
    assert _parse_ps("   \n ") == []


@_docker
async def test_the_compose_adapter_reaches_the_daemon_for_an_unknown_project() -> None:
    """A project that was never started observes as empty rather than raising.

    Run only where Docker is present. It is the one assertion that cannot be
    made against a fixture: that the argv this adapter builds is one the daemon
    accepts — and, since Compose interpolates the template for `ps` as well as
    for `up`, that the template is interpolable without the variables only an
    `apply` can supply.
    """
    driver = ComposeDriver(compose_file="deploy/single/docker-compose.serving.yml")

    observation = await driver.observe(uuid.uuid4())

    assert observation.live_count == 0
