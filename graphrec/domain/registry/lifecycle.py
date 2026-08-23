"""What decides a version's status, and what the console may do with it.

Two questions, both answered here so they cannot be answered differently in two
places. The first is the floor: a freshly trained version is `registered`, and
something has to turn that into `eligible` or `rejected`. The second is gate 5:
the console disables Activate, Roll back and Archive with a stated reason, and
the endpoint that would refuse the same request must refuse it for the same
reason (BUILD_PROMPT §gate-5).

**The floor is the popularity baseline, plus a minimum.** CON-01 makes the
popularity ranker "a floor, not a peer": a version that cannot beat recommending
the top sellers has no business serving traffic, whatever its absolute numbers
say. The absolute minimum is the second half, because a baseline that is itself
near zero — a catalogue with almost no repeat behaviour — is beatable by noise.
A version must clear both.

**The floor is calibrated against ADR 0024's protocol, not against a paper.**
Evaluation here ranks the whole catalogue rather than a sampled subset, which
produces numbers roughly three times lower than the sampled-negative figures
published for DGSR. A floor imported from a paper would reject every version
this system will ever train. The defaults below are therefore deliberately
modest in absolute terms and strict in relative terms, which is also the right
shape: "better than popularity" is a claim that means the same thing on every
catalogue, and "recall@10 above 0.2" does not.

**Rejection is not failure.** A `rejected` version keeps its row, its metrics
and its artifact; it is a measurement a tenant can look at and compare against
the next run. Only `archived` destroys anything (ADR 0027).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from graphrec.common.enums import ModelVersionStatus
from graphrec.common.error_copy import resolve_copy

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The measure the floor is applied to. One measure, not four: a version that
#: has to clear four independent floors is a version rejected by whichever
#: measure happened to be noisiest, and recall@10 is the one the console leads
#: with (L1730) and the one UC-17 names.
FLOOR_METRIC = "recall_at_10"

#: How much better than the popularity baseline a version must be, as a ratio.
#: 1.05 rather than 1.0: a version that ties the baseline within measurement
#: noise has not demonstrated anything, and the cost of waiting for the next
#: run is one training job.
DEFAULT_BASELINE_RATIO = 1.05

#: The absolute floor on `FLOOR_METRIC`. Low, because ADR 0024's full-catalogue
#: protocol produces low numbers by construction; the relative test above is
#: what does the real work.
DEFAULT_MINIMUM = 0.01

#: How the two numbers are rendered into the tenant's sentence. Three places,
#: because these are ratios in [0, 1] and two places turns 0.018 into 0.02.
_PLACES = 3


@dataclass(frozen=True, slots=True)
class MetricFloor:
    """The two tests a version must pass to become `eligible`."""

    metric: str = FLOOR_METRIC
    baseline_ratio: float = DEFAULT_BASELINE_RATIO
    minimum: float = DEFAULT_MINIMUM


@dataclass(frozen=True, slots=True)
class Verdict:
    """The status registration writes, and the note that explains it.

    `note` is `None` when eligible. `ck_model_versions_failure_note` refuses a
    note on a version that has nothing to explain, so this is the schema's rule
    restated where the value is produced.
    """

    status: ModelVersionStatus
    note: str | None

    @property
    def eligible(self) -> bool:
        return self.status is ModelVersionStatus.ELIGIBLE


def judge(
    measured: Mapping[str, float],
    baseline: Mapping[str, float],
    floor: MetricFloor | None = None,
) -> Verdict:
    """Apply the floor to one run's measurements.

    The baseline test comes first. A version below both is more usefully told it
    lost to popularity than that it missed an absolute number, because the first
    is a statement about the model and the second is a statement about the
    catalogue.

    A missing measure is a rejection, not a crash. It means the evaluator did
    not produce the measure the floor is defined on, and a version admitted
    because nobody could measure it is the one outcome this function exists to
    prevent.
    """
    rule = floor or MetricFloor()
    value = measured.get(rule.metric)
    reference = baseline.get(rule.metric)
    if value is None or reference is None:
        return Verdict(
            status=ModelVersionStatus.REJECTED,
            note=resolve_copy(
                "model_version_below_minimum",
                measured=_render(value),
                metric=rule.metric,
                minimum=_render(rule.minimum),
            ),
        )

    if value < reference * rule.baseline_ratio:
        return Verdict(
            status=ModelVersionStatus.REJECTED,
            note=resolve_copy(
                "model_version_below_baseline",
                measured=_render(value),
                metric=rule.metric,
                baseline=_render(reference),
            ),
        )
    if value < rule.minimum:
        return Verdict(
            status=ModelVersionStatus.REJECTED,
            note=resolve_copy(
                "model_version_below_minimum",
                measured=_render(value),
                metric=rule.metric,
                minimum=_render(rule.minimum),
            ),
        )
    return Verdict(status=ModelVersionStatus.ELIGIBLE, note=None)


def _render(value: float | None) -> str:
    return "no measurement" if value is None else f"{value:.{_PLACES}f}"


# --------------------------------------------------------------------- gate 5


@dataclass(frozen=True, slots=True)
class Action:
    """One control, why it is disabled, and the code that refuses it.

    `reason` is `None` when allowed, matching BACKEND_PLAN L1155. The prototype
    uses `''` there; the wire spec uses `null`, and `null` is the one a client
    cannot accidentally render.

    `code` is carried alongside so the endpoint can raise the refusal the button
    describes without a second table mapping sentences back to codes. It is not
    on the wire inside `actions` — the error envelope is where a code belongs —
    but it is what makes "the disabled reason and the 409 are the same fact"
    true by construction rather than by review.
    """

    allowed: bool
    reason: str | None
    code: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"allowed": self.allowed, "reason": self.reason}


def _refuse(code: str) -> Action:
    return Action(allowed=False, reason=resolve_copy(code), code=code)


@dataclass(frozen=True, slots=True)
class VersionContext:
    """What the three predicates need to know about the rest of the registry.

    Read once per detail request rather than derived per action, because all
    three questions are about the same two facts and asking twice is how they
    come to disagree mid-request.
    """

    #: The active version's number, if a version is active.
    active_number: int | None
    #: Whether any version is `retired` — a rollback needs a target to exist.
    has_retired: bool


def can_activate(status: ModelVersionStatus) -> Action:
    """L1768: eligible only, and "already active" is its own sentence."""
    if status is ModelVersionStatus.ELIGIBLE:
        return Action(allowed=True, reason=None)
    return _refuse(
        "version_already_active" if status is ModelVersionStatus.ACTIVE else "version_not_eligible"
    )


def can_rollback(status: ModelVersionStatus, context: VersionContext) -> Action:
    """L1769, verbatim in structure: rollback is an operation *on the active
    version*, so it is offered on the active version's page and requires a
    retained target to exist."""
    if status is ModelVersionStatus.ACTIVE and context.has_retired:
        return Action(allowed=True, reason=None)
    return _refuse("rollback_requires_target")


def can_archive(status: ModelVersionStatus, version_number: int, context: VersionContext) -> Action:
    """L1748-1749, including the rule that protects a rollback target.

    The prototype's predicate is
    `['registered','rejected','retired'].indexOf(v.status)>=0 &&
     !(v.status==='retired' && act && act.n - v.n <= 1)`.
    The second half reads oddly until it is read as an inequality: a retired
    version is protected when its number is within one of the active version's,
    which is the immediately preceding version *and* anything numbered above the
    active one. That is not a mistake in the prototype. A retired version with a
    higher number than the active one is a version that was rolled back *from*,
    and it is exactly as much a rollback target as the one below.
    """
    if status is ModelVersionStatus.ACTIVE:
        return _refuse("archive_active_version")
    if status is ModelVersionStatus.ARCHIVED:
        return _refuse("archive_already_archived")
    if status not in _ARCHIVABLE:
        # `eligible` and `failed_deployment` fall here. Neither is archivable
        # and neither has a sentence of its own in the prototype, which only
        # ever renders this page for the five statuses above; the honest reason
        # is the general one rather than an invented specific.
        return _refuse("version_not_eligible")
    if (
        status is ModelVersionStatus.RETIRED
        and context.active_number is not None
        and context.active_number - version_number <= 1
    ):
        return _refuse("archive_rollback_target")
    return Action(allowed=True, reason=None)


_ARCHIVABLE = frozenset(
    {
        ModelVersionStatus.REGISTERED,
        ModelVersionStatus.REJECTED,
        ModelVersionStatus.RETIRED,
    }
)


__all__ = [
    "DEFAULT_BASELINE_RATIO",
    "DEFAULT_MINIMUM",
    "FLOOR_METRIC",
    "Action",
    "MetricFloor",
    "Verdict",
    "VersionContext",
    "can_activate",
    "can_archive",
    "can_rollback",
    "judge",
]
