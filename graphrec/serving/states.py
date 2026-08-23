"""The serving path's own vocabulary.

`graphrec/common/enums.py` is generated from the console prototype and must not
be edited by hand, which is the right rule and also means it cannot hold any of
this. The data plane has **no console surface at all** (BACKEND_PLAN L564): the
prototype never renders a strategy, a candidate source or a replica status, so
none of them appears in its `GROUPS`. They are still part of the API contract —
ER-F-05 makes `strategy` mandatory in every recommendation response — so they
live here, in the module that owns them, exactly as the nine-stage rail lives in
`graphrec.training.states`.

`DeploymentState` is the exception and is *not* here: the console draws it as a
badge (dc.html L1827), so it is generated with the rest of the prototype's
vocabulary and imported.
"""

from __future__ import annotations

from enum import StrEnum

from graphrec.common.enums import DeploymentState


class Strategy(StrEnum):
    """How a response was produced (BACKEND_PLAN L1277).

    Four values, in decreasing order of how much the system knew about the
    caller. A tenant reading `fallback` on a request they expected to be
    `personalized` is reading the one number that explains a metrics change,
    which is why ER-F-05 makes it mandatory rather than optional.
    """

    #: A known customer with resident history: the model scored real candidates.
    PERSONALIZED = "personalized"
    #: No customer, but a session with events in it. XR-F-09's blend, with the
    #: short-term half doing all of the work.
    SESSION = "session"
    #: Neither history nor session. Popularity and category, by design rather
    #: than by failure — this is a correct answer to a cold request.
    COLD_START = "cold_start"
    #: The model could not answer and `allow_fallback` was true. ER-F-10. This
    #: is the only one of the four that reports a degradation.
    FALLBACK = "fallback"


#: The strategies that mean the model answered. A response outside this set is
#: one a tenant may want to alert on; one inside it is not.
MODEL_STRATEGIES = frozenset({Strategy.PERSONALIZED, Strategy.SESSION})


class CandidateSource(StrEnum):
    """Where a candidate came from, per item (BACKEND_PLAN L1280).

    Carried on every result row because the four-stage funnel draws from up to
    four places and a tenant debugging a bad recommendation needs to know which.
    `recommendation_results.candidate_source` stores it.
    """

    #: The DGSR item embeddings, through the candidate index.
    GRAPH = "graph"
    #: The tenant's own recent interaction counts.
    POPULARITY = "popularity"
    #: Same category as something the caller just touched.
    CATEGORY = "category"
    #: Drawn from the session's own events rather than from the catalogue.
    SESSION = "session"


class ReplicaStatus(StrEnum):
    """One serving process's lifecycle, as the driver reports it.

    `ready` is a separate boolean rather than a status value: a replica can be
    `running` and not yet ready, and collapsing the two would make
    "desired 3 / ready 3" true the instant three containers existed rather than
    when three of them could answer.
    """

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


#: A replica that still counts toward capacity. A `stopped` or `failed` one does
#: not, and the reconciler replaces it rather than waiting for it.
LIVE_REPLICA_STATUSES = frozenset(
    {ReplicaStatus.STARTING, ReplicaStatus.RUNNING, ReplicaStatus.STOPPING}
)


class RevisionStatus(StrEnum):
    """One attempt to change what is serving.

    `deployment_revisions` is "the rollback and failed-activation history"
    (BACKEND_PLAN L845), so a failure is a row rather than an absence: a tenant
    asking why version 8 is not serving is asking to read this table.
    """

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RevisionKind(StrEnum):
    """Why the change was attempted.

    A rollback and an activation move the same two columns and mean opposite
    things, and a history that could not tell them apart would be a history that
    could not answer "has this tenant ever rolled back".
    """

    ACTIVATION = "activation"
    ROLLBACK = "rollback"
    STOP = "stop"


class FeedbackType(StrEnum):
    """The three feedback surfaces (BACKEND_PLAN L1256-1258).

    Informational only. ASM-05: feedback never auto-activates a model, so
    nothing in the activation path reads this.
    """

    IMPRESSION = "impression"
    CLICK = "click"
    CONVERSION = "conversion"


class RequestStatus(StrEnum):
    """How a recommendation request ended.

    Recorded on `recommendation_requests` so `/v1/metrics/summary` can compute
    availability from rows rather than from a metrics scrape that may be
    unreachable — the same discipline usage follows: a measurement that is
    missing is reported as missing, not as zero.
    """

    SERVED = "served"
    DEGRADED = "degraded"
    REFUSED = "refused"


class ServingErrorClass(StrEnum):
    """The only thing `/v1/service-status/errors` is allowed to say happened.

    dc.html L1842 states the rule the column exists to enforce: "Error classes
    only. Request payloads and recommendation results are never rendered here."
    A class is a bucket the console can draw a badge from; it cannot carry a
    customer identifier or a product list, because it is drawn from this closed
    set and nowhere else.
    """

    UNAVAILABLE = "unavailable"
    VALIDATION = "validation"
    INTERNAL = "internal"


#: The states in which a deployment is doing what it was asked to do. Anything
#: else is drawn amber or red on `/service-status` (L1835).
HEALTHY_DEPLOYMENT_STATES = frozenset({DeploymentState.AVAILABLE})

#: A deployment mid-change. The reconciler will not begin a second change while
#: a deployment is in one of these.
TRANSITIONAL_DEPLOYMENT_STATES = frozenset(
    {DeploymentState.PENDING, DeploymentState.PROGRESSING, DeploymentState.ROLLING_BACK}
)


__all__ = [
    "HEALTHY_DEPLOYMENT_STATES",
    "LIVE_REPLICA_STATUSES",
    "MODEL_STRATEGIES",
    "TRANSITIONAL_DEPLOYMENT_STATES",
    "CandidateSource",
    "FeedbackType",
    "ReplicaStatus",
    "RequestStatus",
    "RevisionKind",
    "RevisionStatus",
    "ServingErrorClass",
    "Strategy",
]
