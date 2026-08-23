"""The orchestration port: four verbs, and what a driver is not allowed to know.

ADR 0028. A `ServingDriver` starts, observes and stops inference processes for
one tenant. Compose is the adapter that ships; k3s is the one the port exists
for.

**The port is desired-state, not imperative.** `apply` is given a whole
`DesiredState` and is responsible for reaching it — not `scale_up(1)`. Two
callers racing on an imperative interface produce a count nobody asked for;
two callers racing on this one produce the same count twice.

**The driver never decides anything.** It does not choose a version, does not
know what `available` means, does not enforce `ready >= 1`. It reports what it
sees and does what it is told, and every judgement lives in
`graphrec.domain.serving.reconciler` — because that judgement has to be
identical under Compose and under k3s, and a rule implemented in an adapter is
a rule implemented twice.

**`observe` returns the truth, including inconvenient truth.** A replica that is
running last week's version is reported with last week's version id rather than
omitted or corrected. The reconciler is what notices the drift; a driver that
tidied it away would make `ready_replicas` a number that counts processes rather
than capacity.

**Failure is a return value where it is expected and an exception where it is
not.** `apply` returning fewer replicas than asked for is Tuesday — the host is
full, an image is pulling. `DriverError` is for "I could not talk to the
orchestrator at all", which is the case where retrying later is the only
sensible response and where the deployment must not be marked failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from graphrec.serving.states import ReplicaStatus

if TYPE_CHECKING:
    import datetime as dt
    import uuid


class DriverError(RuntimeError):
    """The orchestrator could not be reached or refused to answer.

    Transient. Distinct from "the orchestrator answered and the answer was no
    replicas": that is an `Observation` with nothing ready in it, which the
    reconciler handles by leaving the deployment `progressing` until it either
    settles or the activation times out.
    """


@dataclass(frozen=True, slots=True)
class DesiredState:
    """What one tenant's serving should look like.

    `version_id` and `bundle_uri` travel together on purpose. The driver hands
    the URI to the process it starts, and the id is what the process reports
    back — so a replica claiming a version it was never given is visible as a
    mismatch rather than as a coincidence nobody checks.
    """

    tenant_id: uuid.UUID
    version_id: uuid.UUID
    bundle_uri: str
    replicas: int
    #: Bumped by the control plane on every change to desired state. Passed to
    #: the process so `observe` can tell a replica started for *this* desired
    #: state from one left over from the previous.
    epoch: int


@dataclass(frozen=True, slots=True)
class ReplicaObservation:
    """One process, as the orchestrator describes it.

    `ready` is separate from `status` because a container can be `running` and
    unable to answer — it is still loading a bundle. Collapsing them would make
    "3 of 3 ready" true the moment three containers existed.
    """

    replica_ref: str
    status: ReplicaStatus
    ready: bool
    version_id: uuid.UUID | None
    epoch: int | None = None
    started_at: dt.datetime | None = None
    #: The orchestrator's own words, kept for `/service-status` and never shown
    #: to a tenant — it is an image name or an exit code, not approved copy.
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything the driver can see about one tenant right now."""

    tenant_id: uuid.UUID
    replicas: tuple[ReplicaObservation, ...] = field(default_factory=tuple)

    @property
    def ready_count(self) -> int:
        return sum(1 for replica in self.replicas if replica.ready)

    @property
    def live_count(self) -> int:
        """Processes that exist, ready or not — what `desired` is compared
        against when deciding whether to start more."""
        return sum(
            1
            for replica in self.replicas
            if replica.status in {ReplicaStatus.STARTING, ReplicaStatus.RUNNING}
        )

    def serving(self, version_id: uuid.UUID) -> int:
        """How many ready replicas are answering with a given version.

        The load-before-swap check (ER-F-06) is exactly this number reaching one
        for the new version, which is why it is a method here rather than a
        comprehension written out at each call site.
        """
        return sum(1 for r in self.replicas if r.ready and r.version_id == version_id)


@dataclass(frozen=True, slots=True)
class DriverInfo:
    """What `describe` answers, for `/admin/status` and for a log line at boot.

    `supports_multi_node` is the one field with teeth: it is `False` under
    Compose, which is why ASM-02 bounds the local installation at four tenants.
    """

    kind: str
    supports_multi_node: bool
    max_replicas_per_tenant: int


@runtime_checkable
class ServingDriver(Protocol):
    """Start, look, stop, describe. Nothing else."""

    async def apply(self, desired: DesiredState) -> Observation:
        """Converge toward `desired` and report what exists afterwards.

        Idempotent: applying the same `DesiredState` twice is one call's worth
        of effect. That is what lets the reconciler run on a timer without
        tracking whether it already acted.
        """
        ...

    async def observe(self, tenant_id: uuid.UUID) -> Observation:
        """Report the current replicas without changing anything."""
        ...

    async def stop(self, tenant_id: uuid.UUID) -> Observation:
        """Take everything down for one tenant.

        Returns the observation afterwards rather than `None`, so a stop that
        left something behind is visible to the caller instead of being assumed.
        """
        ...

    def describe(self) -> DriverInfo:
        """Static facts about this adapter. Synchronous: it asks nothing."""
        ...


__all__ = [
    "DesiredState",
    "DriverError",
    "DriverInfo",
    "Observation",
    "ReplicaObservation",
    "ServingDriver",
]
