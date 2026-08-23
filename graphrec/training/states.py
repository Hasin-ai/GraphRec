"""The nine-stage rail, and the three ways off it.

`graphrec.common.enums.JobState` has twelve values. Nine of them are positions
on the console's pipeline rail (dc.html L632); the other three — `cancelling`,
`cancelled`, `failed` — are things that happen *to* a run rather than places it
reaches. That distinction is the whole of this module, and getting it wrong is
how a rail ends up trying to render `failed` as its tenth stage.

So `STAGE_RAIL` is the ordered nine, `stage_index` is an offset into it, and a
terminal state carries the index it stopped at rather than an index of its own.
A failed job is "stopped at `building_graph`", which the state alone cannot say.

The rail's last position, `succeeded`, is also a terminal state. That is not a
contradiction: succeeding *is* reaching the end of the pipeline, whereas failing
and being cancelled are departures from it. The console draws the same
conclusion — L1690 takes `JOB_STAGES.indexOf(j.state)` for a live or successful
job and the stored `stageAt` for a failed or cancelled one.
"""

from __future__ import annotations

from graphrec.common.enums import JobState

#: dc.html L632, in order. An offset into this tuple is a `stage_index`.
STAGE_RAIL: tuple[JobState, ...] = (
    JobState.QUEUED,
    JobState.WAITING_FOR_RESOURCES,
    JobState.PREPARING_DATA,
    JobState.BUILDING_GRAPH,
    JobState.TRAINING,
    JobState.EVALUATING,
    JobState.INDEXING_EMBEDDINGS,
    JobState.REGISTERING,
    JobState.SUCCEEDED,
)

#: The wire form, which is what `GET /v1/training-jobs/{id}` returns as `stages`
#: so the client never hard-codes the rail it renders.
STAGE_NAMES: tuple[str, ...] = tuple(state.value for state in STAGE_RAIL)

#: A run is over. Matches migration 0010's `TERMINAL_TRAINING_STATES` and the
#: partial unique index built from it.
TERMINAL_STATES = frozenset({JobState.CANCELLED, JobState.FAILED, JobState.SUCCEEDED})

#: L1688 — "Only a job in an active state can be cancelled." Nine states, and
#: `cancelling` is among them: asking twice is not an error, it is the same ask.
ACTIVE_STATES = frozenset(JobState) - TERMINAL_STATES

#: The eight the worker actually moves through while doing work. `succeeded` is
#: reached by finishing, not by entering.
WORKING_STAGES: tuple[JobState, ...] = STAGE_RAIL[:-1]


def stage_index(state: JobState) -> int:
    """Where `state` sits on the rail.

    A state that is not on the rail has no position, and this refuses to invent
    one — the caller holds the last recorded index for exactly that case. The
    alternative, returning `-1` or `0`, would render a cancelled job as "stopped
    at queued" no matter how far it got.
    """
    try:
        return STAGE_RAIL.index(state)
    except ValueError as exc:
        raise ValueError(f"{state.value!r} is not a position on the stage rail") from exc


def is_on_rail(state: JobState) -> bool:
    return state in STAGE_RAIL


def is_terminal(state: JobState) -> bool:
    return state in TERMINAL_STATES


def is_active(state: JobState) -> bool:
    return state in ACTIVE_STATES


__all__ = [
    "ACTIVE_STATES",
    "STAGE_NAMES",
    "STAGE_RAIL",
    "TERMINAL_STATES",
    "WORKING_STAGES",
    "is_active",
    "is_on_rail",
    "is_terminal",
    "stage_index",
]
