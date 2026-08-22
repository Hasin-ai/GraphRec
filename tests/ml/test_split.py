"""The temporal leave-last-out split — and the leakage test that gates Phase 8.

BUILD_PROMPT's exit criterion for this phase is two things: the model beats the
popularity baseline, and *the leakage test passes*. This is that test. It is
written as several small ones rather than one, because "no leakage" has at least
four distinct failure modes and a single assertion that happened to catch one of
them would read as though it covered all four.

The deliberately-broken cases matter as much as the passing ones. A leakage
check that has never been shown to fail is a leakage check nobody should trust,
so `assert_no_leakage` is fed a corrupted split and required to raise.
"""

from __future__ import annotations

import datetime as dt

import pytest

from graphrec.common.enums import EventType
from graphrec.ml.eval.split import MIN_INTERACTIONS, HeldOut, LeakageError, Split, leave_last_out
from graphrec.ml.features.builder import FeatureBuilder, Interaction

BASE = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)


def view(user: str, item: str, hours: int) -> Interaction:
    return Interaction(
        user_ref=user,
        item_ref=item,
        event_type=EventType.VIEW,
        occurred_at=BASE + dt.timedelta(hours=hours),
    )


def five_interactions() -> Split:
    rows = [view("u1", f"i{n}", n) for n in range(5)]
    return leave_last_out(FeatureBuilder().build(rows))


# ------------------------------------------------------------------ the rule


def test_the_last_interaction_is_the_test_target() -> None:
    split = five_interactions()

    assert split.test[0].item == split.train.item_refs.index("i4")


def test_the_second_to_last_is_validation() -> None:
    split = five_interactions()

    assert split.validation[0].item == split.train.item_refs.index("i3")


def test_training_keeps_everything_earlier() -> None:
    split = five_interactions()

    kept = [split.train.item_refs[i] for i in split.train.sequences[0]]
    assert kept == ["i0", "i1", "i2"]


def test_the_test_history_includes_the_validation_interaction() -> None:
    """Not leakage: at serving time the model would have it, because by then it
    is the past. Excluding it would make the offline task harder than the real
    one."""
    split = five_interactions()

    assert len(split.test[0].history) == 4
    assert split.validation[0].item in split.test[0].history


def test_the_validation_history_stops_before_the_validation_target() -> None:
    split = five_interactions()

    assert split.validation[0].item not in split.validation[0].history
    assert len(split.validation[0].history) == 3


# ------------------------------------------------- who is and is not scored


@pytest.mark.parametrize("count", [1, 2])
def test_a_user_below_the_threshold_stays_wholly_in_training(count: int) -> None:
    """Scoring a user with one interaction measures the popularity prior and
    calls it the model."""
    rows = [view("u1", f"i{n}", n) for n in range(count)]
    split = leave_last_out(FeatureBuilder().build(rows))

    assert len(split.train.sequences[0]) == count
    assert split.validation == []
    assert split.test == []


def test_three_interactions_is_the_threshold() -> None:
    rows = [view("u1", f"i{n}", n) for n in range(MIN_INTERACTIONS)]
    split = leave_last_out(FeatureBuilder().build(rows))

    assert len(split.test) == 1
    assert len(split.train.sequences[0]) == 1


def test_indices_are_preserved_across_the_split() -> None:
    """Reindexing would be tidier and would break every checkpoint: an item's
    integer has to mean the same thing in the split, the graph, the trained
    table and the exported bundle."""
    dataset = FeatureBuilder().build([view("u1", f"i{n}", n) for n in range(5)])
    split = leave_last_out(dataset)

    assert split.train.item_refs == dataset.item_refs
    assert split.train.user_refs == dataset.user_refs
    assert split.train.n_items == dataset.n_items


# ------------------------------------------------------------- the criterion


def test_the_fixture_split_has_no_leakage(split) -> None:
    """The Phase 8 exit criterion, on the real fixture."""
    split.assert_no_leakage()


def test_every_test_target_is_strictly_later_than_every_training_row(split) -> None:
    latest = {user: max(times) for user, times in enumerate(split.train.timestamps) if times}
    for row in split.test:
        assert row.occurred_at > latest[row.user]


def test_no_held_out_triple_appears_in_training(split) -> None:
    triples = {
        (user, item, when)
        for user, (seq, times) in enumerate(
            zip(split.train.sequences, split.train.timestamps, strict=True)
        )
        for item, when in zip(seq, times, strict=True)
    }
    for row in [*split.validation, *split.test]:
        assert (row.user, row.item, row.occurred_at) not in triples


def test_every_scored_user_has_a_history_to_predict_from(split) -> None:
    for row in [*split.validation, *split.test]:
        assert row.history, "an empty history makes the score a popularity prior"


# --------------------------------------- the check is shown to actually fail


def test_a_target_left_in_training_is_caught() -> None:
    split = five_interactions()
    leaked = Split(
        train=split.train,
        validation=split.validation,
        test=[
            HeldOut(
                user=0,
                item=split.train.sequences[0][0],
                occurred_at=split.train.timestamps[0][0],
                history=[],
            )
        ],
    )

    with pytest.raises(LeakageError, match="is also a training row"):
        leaked.assert_no_leakage()


def test_a_target_before_a_training_row_is_caught() -> None:
    """The temporal half: predicting the user's own past."""
    split = five_interactions()
    leaked = Split(
        train=split.train,
        validation=[],
        test=[
            HeldOut(
                user=0,
                item=99,
                occurred_at=BASE - dt.timedelta(hours=1),
                history=[],
            )
        ],
    )

    with pytest.raises(LeakageError, match="predicting its own past"):
        leaked.assert_no_leakage()


def test_the_error_names_which_side_leaked() -> None:
    split = five_interactions()
    leaked = Split(
        train=split.train,
        validation=[
            HeldOut(
                user=0,
                item=split.train.sequences[0][1],
                occurred_at=split.train.timestamps[0][1],
                history=[],
            )
        ],
        test=[],
    )

    with pytest.raises(LeakageError, match="^validation target"):
        leaked.assert_no_leakage()


def test_leakage_error_is_an_assertion_error() -> None:
    """Never a caller's bad input — the split being wrong, and the only correct
    response is for the run to stop."""
    assert issubclass(LeakageError, AssertionError)
