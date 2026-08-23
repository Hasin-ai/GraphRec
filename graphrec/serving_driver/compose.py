"""The Compose adapter, and the local driver that stands in for it.

Two implementations of one port. `ComposeDriver` shells out to
`docker compose`; `InProcessDriver` keeps replicas in a dictionary. The second
is not a mock — it is what a single-process local run and the whole test suite
actually use, and it is held to the same contract by the same tests
(`tests/serving/test_driver_contract.py` parametrises over both).

**Compose scales a service, it does not schedule.** `docker compose up
--scale svc=N` puts all N containers on the machine that ran the command, which
is ADR 0028's admitted limit and the reason ASM-02 bounds the local
installation at four tenants. The port hides the difference in *interface*, not
in capability: `describe().supports_multi_node` reports it honestly so
`/admin/status` can say so rather than implying a cluster.

**One Compose project per tenant.** `graphrec-serve-{tenant hex}` — a namespace
per tenant means `stop` cannot reach another tenant's containers even if the
label filter were wrong, and it makes the container names the driver reports
stable across restarts.

**Every argument is a literal, never a shell string.** The subprocess is spawned
with an argument vector, so a tenant id is a value and not something that could
be read as an option. Nothing here interpolates user input into a command line;
the only variable parts are a UUID hex, an integer and a URI the control plane
produced.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import shutil
import uuid
from dataclasses import dataclass, replace
from typing import Any

from graphrec.serving.states import ReplicaStatus
from graphrec.serving_driver.driver import (
    DesiredState,
    DriverError,
    DriverInfo,
    Observation,
    ReplicaObservation,
)

#: The Compose project name per tenant. Hex rather than the dashed form because
#: Compose lowercases and strips project names, and a name it rewrote would be a
#: name `stop` could not find again.
PROJECT_PREFIX = "graphrec-serve-"

#: The service inside that project. One service, scaled — not N services.
SERVICE_NAME = "inference"

#: How long a Compose command may take before it is a `DriverError`. Generous,
#: because an image pull is inside it; bounded, because a reconciler blocked on
#: a hung `docker` holds the leader lock and nothing else converges.
COMMAND_TIMEOUT_SECONDS = 120.0

#: Compose gives four values here. Mapped rather than passed through, so a
#: Docker upgrade that adds a fifth is a `KeyError` in one place instead of a
#: string that fails a check constraint at INSERT time.
_COMPOSE_STATES = {
    "created": ReplicaStatus.STARTING,
    "restarting": ReplicaStatus.STARTING,
    "running": ReplicaStatus.RUNNING,
    "removing": ReplicaStatus.STOPPING,
    "paused": ReplicaStatus.STOPPING,
    "exited": ReplicaStatus.STOPPED,
    "dead": ReplicaStatus.FAILED,
}

#: Docker's own health vocabulary. `starting` is explicitly *not* ready, which
#: is the distinction the `ready` column exists for.
_READY_HEALTH = "healthy"


def project_name(tenant_id: uuid.UUID) -> str:
    return f"{PROJECT_PREFIX}{tenant_id.hex}"


@dataclass(frozen=True, slots=True)
class ComposeDriver:
    """Drives `docker compose` for one installation.

    `compose_file` is the tenant-parameterised template shipped in `deploy/`.
    It is passed with `-f` rather than discovered from the working directory,
    because a reconciler's working directory is not a thing to depend on.
    """

    compose_file: str
    binary: str = "docker"
    image: str | None = None

    async def apply(self, desired: DesiredState) -> Observation:
        """`up -d --scale`, then look.

        Compose is already desired-state, so this is close to a pass-through —
        which is the point of choosing it. The environment carries what the
        process needs to pin itself: `GRAPHREC_TENANT_ID`, the version and the
        bundle it must load, and the epoch it was started for.
        """
        env = {
            "GRAPHREC_TENANT_ID": str(desired.tenant_id),
            "GRAPHREC_MODEL_VERSION_ID": str(desired.version_id),
            "GRAPHREC_BUNDLE_URI": desired.bundle_uri,
            "GRAPHREC_DEPLOY_EPOCH": str(desired.epoch),
        }
        if self.image is not None:
            env["GRAPHREC_INFERENCE_IMAGE"] = self.image
        await self._compose(
            desired.tenant_id,
            "up",
            "--detach",
            "--remove-orphans",
            "--scale",
            f"{SERVICE_NAME}={desired.replicas}",
            SERVICE_NAME,
            env=env,
        )
        return await self.observe(desired.tenant_id)

    async def observe(self, tenant_id: uuid.UUID) -> Observation:
        """`compose ps --format json`, mapped onto the port's vocabulary."""
        raw = await self._compose(tenant_id, "ps", "--all", "--format", "json")
        return Observation(tenant_id=tenant_id, replicas=tuple(_parse_ps(raw)))

    async def stop(self, tenant_id: uuid.UUID) -> Observation:
        """`down`, then confirm.

        `--volumes` is deliberately absent. A tenant's serving containers hold
        no state worth keeping, but a driver that removes volumes is a driver
        one misrouted tenant id away from removing something that does.
        """
        await self._compose(tenant_id, "down", "--remove-orphans")
        return await self.observe(tenant_id)

    def describe(self) -> DriverInfo:
        return DriverInfo(
            kind="compose",
            # ADR 0028's admitted limit, reported rather than hidden.
            supports_multi_node=False,
            max_replicas_per_tenant=8,
        )

    async def _compose(
        self, tenant_id: uuid.UUID, *args: str, env: dict[str, str] | None = None
    ) -> str:
        if shutil.which(self.binary) is None:
            msg = f"{self.binary} is not on PATH; serving_driver=compose cannot run"
            raise DriverError(msg)
        argv = (
            self.binary,
            "compose",
            "--project-name",
            project_name(tenant_id),
            "--file",
            self.compose_file,
            *args,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_environment(env),
            )
        except OSError as exc:  # pragma: no cover - depends on the host
            msg = f"could not start {self.binary} compose"
            raise DriverError(msg) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=COMMAND_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            # Kill it. A `docker compose up` left running after the reconciler
            # gave up on it is the one way two drivers can act on one tenant.
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            msg = f"{self.binary} compose {args[0]} did not finish in time"
            raise DriverError(msg) from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", "replace").strip()[:500]
            msg = f"{self.binary} compose {args[0]} failed: {detail}"
            raise DriverError(msg)
        return stdout.decode("utf-8", "replace")


def _environment(extra: dict[str, str] | None) -> dict[str, str] | None:
    """The parent environment plus what the service template reads.

    `None` when there is nothing to add, so the child inherits normally rather
    than being handed a copy that could go stale.
    """
    if not extra:
        return None
    import os

    return {**os.environ, **extra}


def _parse_ps(raw: str) -> list[ReplicaObservation]:
    """Compose's `ps --format json` is JSON *lines*, not a JSON array.

    It has been both across Docker versions, so both are accepted. A parse
    failure is skipped rather than raised: one unreadable line should cost one
    replica's visibility, not the whole observation — the reconciler treats a
    missing replica as one to start, which is the safe direction.
    """
    text = raw.strip()
    if not text:
        return []
    documents: list[Any]
    if text.startswith("["):
        try:
            documents = json.loads(text)
        except json.JSONDecodeError:
            return []
    else:
        documents = []
        for line in text.splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                documents.append(json.loads(line))

    observations = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        parsed = _one(document)
        if parsed is not None:
            observations.append(parsed)
    return observations


def _one(document: dict[str, Any]) -> ReplicaObservation | None:
    name = document.get("Name") or document.get("ID")
    if not name:
        return None
    status = _COMPOSE_STATES.get(str(document.get("State", "")).lower(), ReplicaStatus.FAILED)
    health = str(document.get("Health", "")).lower()
    # No health check configured reports an empty string. Treated as ready when
    # running, because the alternative is a deployment that never converges on
    # a template someone forgot a `healthcheck:` block in — and the inference
    # image does define one, so the empty case is a misconfiguration, not a lie.
    ready = status is ReplicaStatus.RUNNING and health in {_READY_HEALTH, ""}
    labels = _labels(document.get("Labels"))
    return ReplicaObservation(
        replica_ref=str(name),
        status=status,
        ready=ready,
        version_id=_uuid(labels.get("com.graphrec.version")),
        epoch=_int(labels.get("com.graphrec.epoch")),
        detail=str(document.get("Status") or "") or None,
    )


def _labels(value: object) -> dict[str, str]:
    """Compose renders labels as `k=v,k=v`. Older versions used an object."""
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if not isinstance(value, str) or not value:
        return {}
    pairs = {}
    for item in value.split(","):
        key, _, val = item.partition("=")
        if key:
            pairs[key.strip()] = val.strip()
    return pairs


def _uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


class InProcessDriver:
    """Replicas in a dictionary. The local and test driver.

    Deliberately not a `Mock`. The reconciler's convergence loop, the
    `ready >= 1` floor and load-before-swap are all tested against this, and a
    stand-in whose `observe` returned whatever the test wanted would test the
    assertions rather than the loop. So this one has real behaviour: a replica
    starts `starting` and not ready, and becomes ready only when `settle()` is
    called — which is how a test writes "the container came up" as an event
    rather than as a state it declared.
    """

    def __init__(self, *, max_replicas: int = 8) -> None:
        self._by_tenant: dict[uuid.UUID, list[ReplicaObservation]] = {}
        self._max_replicas = max_replicas
        #: Set by a test to make the next `apply` start nothing — the shape of
        #: "the host is full", which is what a failed activation looks like from
        #: here. Not an exception: `apply` succeeding with nothing ready is the
        #: case ER-F-06 is about.
        self.refuse_to_start = False

    async def apply(self, desired: DesiredState) -> Observation:
        replicas = self._by_tenant.setdefault(desired.tenant_id, [])
        # Anything on a different version or epoch is replaced, not kept: this
        # is desired state, and a leftover replica answering with the old
        # version is exactly the drift the epoch exists to catch.
        replicas[:] = [
            r
            for r in replicas
            if r.version_id == desired.version_id and r.epoch == desired.epoch and r.ready
        ]
        if not self.refuse_to_start:
            wanted = min(desired.replicas, self._max_replicas)
            while len(replicas) < wanted:
                replicas.append(
                    ReplicaObservation(
                        replica_ref=f"{project_name(desired.tenant_id)}-{uuid.uuid4().hex[:8]}",
                        status=ReplicaStatus.STARTING,
                        ready=False,
                        version_id=desired.version_id,
                        epoch=desired.epoch,
                        started_at=dt.datetime.now(dt.UTC),
                    )
                )
            del replicas[wanted:]
        return await self.observe(desired.tenant_id)

    async def observe(self, tenant_id: uuid.UUID) -> Observation:
        return Observation(tenant_id=tenant_id, replicas=tuple(self._by_tenant.get(tenant_id, [])))

    async def stop(self, tenant_id: uuid.UUID) -> Observation:
        self._by_tenant[tenant_id] = []
        return await self.observe(tenant_id)

    def describe(self) -> DriverInfo:
        return DriverInfo(
            kind="inprocess", supports_multi_node=False, max_replicas_per_tenant=self._max_replicas
        )

    # ------------------------------------------------------------- test hooks

    def settle(self, tenant_id: uuid.UUID) -> None:
        """Every starting replica finishes loading its bundle."""
        replicas = self._by_tenant.get(tenant_id, [])
        replicas[:] = [
            replace(r, status=ReplicaStatus.RUNNING, ready=True)
            if r.status is ReplicaStatus.STARTING
            else r
            for r in replicas
        ]

    def fail(self, tenant_id: uuid.UUID) -> None:
        """Every replica dies — a bundle that would not load, an image that
        would not pull. The deployment is `degraded` after this, and whatever
        was already serving keeps serving."""
        replicas = self._by_tenant.get(tenant_id, [])
        replicas[:] = [
            replace(r, status=ReplicaStatus.FAILED, ready=False, detail="exited (1)")
            for r in replicas
        ]


__all__ = [
    "COMMAND_TIMEOUT_SECONDS",
    "PROJECT_PREFIX",
    "SERVICE_NAME",
    "ComposeDriver",
    "InProcessDriver",
    "project_name",
]
