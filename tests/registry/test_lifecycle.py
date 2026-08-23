"""The floor that decides eligibility, and the three gate-5 predicates.

Two things are being pinned. The first is that a version which does not beat the
popularity baseline is `rejected` — CON-01 makes the baseline a floor rather
than a peer, and a registry that admits a model worse than recommending the top
sellers has no defence against R6 (BACKEND_PLAN L1998).

The second is the archive rule, which is the phase's most easily lost
requirement: *"Retained as the rollback target for the active version"* (L1749).
It is enforced in the service rather than by a constraint, because "immediately
preceding" is a question about another row — so this is the test that stands in
for the constraint that cannot exist.
"""

from __future__ import annotations

from graphrec.common.enums import ModelVersionStatus
from graphrec.common.error_copy import resolve_copy
from graphrec.domain.registry import lifecycle

GOOD = {"recall_at_10": 0.21, "ndcg_at_10": 0.18, "coverage": 0.6}
BASELINE = {"recall_at_10": 0.15, "ndcg_at_10": 0.13, "coverage": 0.44}


# --------------------------------------------------------------- the floor


def test_a_version_that_beats_the_baseline_is_eligible() -> None:
    verdict = lifecycle.judge(GOOD, BASELINE)

    assert verdict.status is ModelVersionStatus.ELIGIBLE
    assert verdict.note is None


def test_a_version_below_the_baseline_is_rejected_and_says_both_numbers() -> None:
    """ "Below the floor" without the numbers is a sentence a tenant can do
    nothing with."""
    verdict = lifecycle.judge({"recall_at_10": 0.10}, BASELINE)

    assert verdict.status is ModelVersionStatus.REJECTED
    assert verdict.note is not None
    assert "0.100" in verdict.note
    assert "0.150" in verdict.note


def test_tying_the_baseline_is_not_beating_it() -> None:
    """A version within measurement noise of the baseline has demonstrated
    nothing, and the cost of waiting is one training run."""
    verdict = lifecycle.judge({"recall_at_10": 0.15}, BASELINE)

    assert verdict.status is ModelVersionStatus.REJECTED


def test_clearing_the_baseline_but_not_the_absolute_minimum_is_a_different_reason() -> None:
    """A tenant beats a near-zero baseline by beating noise. The two sentences
    say different things about what to do next."""
    verdict = lifecycle.judge({"recall_at_10": 0.004}, {"recall_at_10": 0.001})

    assert verdict.status is ModelVersionStatus.REJECTED
    assert verdict.note is not None
    assert "below the" in verdict.note


def test_a_missing_measure_is_a_rejection_rather_than_a_crash() -> None:
    """A version admitted because nobody could measure it is the one outcome
    the floor exists to prevent."""
    verdict = lifecycle.judge({"ndcg_at_10": 0.9}, BASELINE)

    assert verdict.status is ModelVersionStatus.REJECTED


def test_the_floor_is_configurable_because_adr_0024_says_it_must_be_calibrated() -> None:
    strict = lifecycle.MetricFloor(baseline_ratio=2.0)

    assert lifecycle.judge(GOOD, BASELINE, strict).status is ModelVersionStatus.REJECTED
    assert lifecycle.judge(GOOD, BASELINE).status is ModelVersionStatus.ELIGIBLE


# --------------------------------------------------------------- gate 5


NOTHING_ACTIVE = lifecycle.VersionContext(active_number=None, has_retired=False)
SERVING_SEVEN = lifecycle.VersionContext(active_number=7, has_retired=True)


def test_only_an_eligible_version_can_be_activated() -> None:
    allowed = lifecycle.can_activate(ModelVersionStatus.ELIGIBLE)
    refused = lifecycle.can_activate(ModelVersionStatus.REGISTERED)

    assert allowed.allowed
    assert allowed.reason is None
    assert not refused.allowed
    assert refused.reason == resolve_copy("version_not_eligible")


def test_the_active_version_has_its_own_sentence() -> None:
    """L1768 distinguishes "already active" from "not eligible", and a console
    that showed the second for the first would be telling a tenant to train
    again."""
    refused = lifecycle.can_activate(ModelVersionStatus.ACTIVE)

    assert refused.reason == resolve_copy("version_already_active")


def test_rollback_is_offered_on_the_active_version_and_needs_a_target() -> None:
    with_target = lifecycle.can_rollback(ModelVersionStatus.ACTIVE, SERVING_SEVEN)
    without = lifecycle.can_rollback(
        ModelVersionStatus.ACTIVE,
        lifecycle.VersionContext(active_number=7, has_retired=False),
    )
    not_active = lifecycle.can_rollback(ModelVersionStatus.ELIGIBLE, SERVING_SEVEN)

    assert with_target.allowed
    assert not without.allowed
    assert not not_active.allowed
    assert without.reason == resolve_copy("rollback_requires_target")


def test_a_registered_or_rejected_version_can_be_archived() -> None:
    for status in (ModelVersionStatus.REGISTERED, ModelVersionStatus.REJECTED):
        decision = lifecycle.can_archive(status, 3, SERVING_SEVEN)
        assert decision.allowed, status
        assert decision.reason is None


def test_the_active_version_cannot_be_archived() -> None:
    decision = lifecycle.can_archive(ModelVersionStatus.ACTIVE, 7, SERVING_SEVEN)

    assert not decision.allowed
    assert decision.reason == resolve_copy("archive_active_version")


def test_an_archived_version_is_already_archived() -> None:
    decision = lifecycle.can_archive(ModelVersionStatus.ARCHIVED, 2, SERVING_SEVEN)

    assert decision.reason == resolve_copy("archive_already_archived")


def test_the_retired_version_immediately_before_the_active_one_is_protected() -> None:
    """L1749, the rule this phase is most likely to lose."""
    decision = lifecycle.can_archive(ModelVersionStatus.RETIRED, 6, SERVING_SEVEN)

    assert not decision.allowed
    assert decision.reason == resolve_copy("archive_rollback_target")


def test_an_older_retired_version_is_not_protected() -> None:
    decision = lifecycle.can_archive(ModelVersionStatus.RETIRED, 5, SERVING_SEVEN)

    assert decision.allowed


def test_a_retired_version_numbered_above_the_active_one_is_also_protected() -> None:
    """`act.n - v.n <= 1` is an inequality, not an off-by-one. A retired version
    numbered above the active one is one that was rolled back *from*, and it is
    exactly as much a rollback target as the one below."""
    decision = lifecycle.can_archive(ModelVersionStatus.RETIRED, 9, SERVING_SEVEN)

    assert not decision.allowed


def test_a_retired_version_is_archivable_when_nothing_is_active() -> None:
    decision = lifecycle.can_archive(ModelVersionStatus.RETIRED, 6, NOTHING_ACTIVE)

    assert decision.allowed


def test_an_eligible_version_is_not_archivable() -> None:
    """The prototype's list is exactly `registered`, `rejected`, `retired`."""
    decision = lifecycle.can_archive(ModelVersionStatus.ELIGIBLE, 8, SERVING_SEVEN)

    assert not decision.allowed


def test_a_refusal_carries_the_code_the_endpoint_raises() -> None:
    """What makes "the disabled button and the 409 are one fact" structural."""
    decision = lifecycle.can_archive(ModelVersionStatus.ACTIVE, 7, SERVING_SEVEN)

    assert decision.code == "archive_active_version"
    assert decision.reason == resolve_copy(decision.code)


def test_an_allowed_action_carries_no_reason() -> None:
    """A reason beside an enabled button is a reason something eventually
    shows."""
    assert lifecycle.can_activate(ModelVersionStatus.ELIGIBLE).as_dict() == {
        "allowed": True,
        "reason": None,
    }
