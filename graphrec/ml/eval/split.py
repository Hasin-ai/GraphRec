"""The temporal leave-last-out split, and the leakage it exists to prevent.

Offline recommendation evaluation is easy to get wrong in exactly one way, and
the way is always the same: the model is scored on an interaction it was
allowed to see. The result is a number that looks excellent, survives review
because nobody can point at the line that causes it, and collapses the day it
serves a real request.

So the split is a first-class module with its own tests rather than four lines
inside a training loop.

**The rule.** For each user with at least `MIN_INTERACTIONS` interactions, the
*last* interaction by time is the test target, the one before it is validation,
and everything earlier is training. Not a random hold-out — a random hold-out
trains on a user's future to predict their past, which is not a task anyone will
ever ask the served model to do.

**The guarantee.** `Split.assert_no_leakage` is not a debugging aid. It is the
Phase 8 exit criterion, and it checks the property directly: no training
interaction may occur at or after the test target it is paired with, and no
held-out `(user, item, time)` triple may appear in the training rows.

**The tie.** Two interactions in the same millisecond are broken by the same
deterministic key `FeatureBuilder` orders by, so the split is reproducible. A
tie broken by set order would silently move an interaction across the boundary
between runs, which is the leakage bug wearing a different hat.

**Users below the threshold** stay wholly in training and are never scored. A
user with one interaction has no history to predict from; scoring them measures
the popularity prior and calls it the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from graphrec.ml.features.builder import Dataset

if TYPE_CHECKING:
    import datetime as dt

#: A user needs one interaction to learn from, one to validate on and one to
#: test on. Below three they are training data only.
MIN_INTERACTIONS = 3


@dataclass(frozen=True, slots=True)
class HeldOut:
    """One user's held-out target."""

    user: int
    item: int
    occurred_at: dt.datetime
    #: The user's training prefix, most recent last. What the sequence pathway
    #: is given at evaluation time, and exactly what inference would have.
    history: list[int]


@dataclass(frozen=True, slots=True)
class Split:
    """Training rows plus two held-out sets.

    `train` is a `Dataset` because everything downstream — graph construction,
    the training loop, the popularity baseline — must be handed the training
    view and never the full one. Making it the same type removes the chance of
    passing the wrong one by accident.
    """

    train: Dataset
    validation: list[HeldOut]
    test: list[HeldOut]

    def assert_no_leakage(self) -> None:
        """Raise `LeakageError` if any held-out interaction is visible to training.

        Two checks, because there are two ways to leak. The first is temporal:
        a training row at or after the target's timestamp means the model saw
        the future. The second is exact: the same triple present on both sides
        means the target was simply not removed.
        """
        seen: set[tuple[int, int, dt.datetime]] = set()
        latest: dict[int, dt.datetime] = {}
        for user, (seq, times) in enumerate(
            zip(self.train.sequences, self.train.timestamps, strict=True)
        ):
            for item, when in zip(seq, times, strict=True):
                seen.add((user, item, when))
                if user not in latest or when > latest[user]:
                    latest[user] = when

        for name, holdout in (("validation", self.validation), ("test", self.test)):
            for row in holdout:
                key = (row.user, row.item, row.occurred_at)
                if key in seen:
                    msg = (
                        f"{name} target (user={row.user}, item={row.item}, "
                        f"at={row.occurred_at.isoformat()}) is also a training row"
                    )
                    raise LeakageError(msg)
                last = latest.get(row.user)
                if last is not None and last >= row.occurred_at:
                    msg = (
                        f"{name} target for user={row.user} occurs at "
                        f"{row.occurred_at.isoformat()}, at or before a training row at "
                        f"{last.isoformat()} — the model would be predicting its own past"
                    )
                    raise LeakageError(msg)


class LeakageError(AssertionError):
    """A held-out interaction was reachable from training.

    An `AssertionError` subclass rather than a `ValueError`, because this is
    never a caller's bad input — it is the split being wrong, and the only
    correct response is for the run to stop.
    """


def leave_last_out(dataset: Dataset, *, min_interactions: int = MIN_INTERACTIONS) -> Split:
    """Split by time, per user, holding out the last two interactions.

    The returned training `Dataset` keeps the *same* item and user indexing as
    the input. Reindexing would be tidier and would break every checkpoint: an
    item's integer has to mean the same thing in the split, in the graph, in the
    trained embedding table and in the exported bundle.
    """
    sequences: list[list[int]] = []
    timestamps: list[list[dt.datetime]] = []
    weights: list[list[float]] = []
    validation: list[HeldOut] = []
    test: list[HeldOut] = []

    for user in range(dataset.n_users):
        seq = dataset.sequences[user]
        times = dataset.timestamps[user]
        wts = dataset.weights[user]

        if len(seq) < min_interactions:
            sequences.append(list(seq))
            timestamps.append(list(times))
            weights.append(list(wts))
            continue

        head = len(seq) - 2
        sequences.append(list(seq[:head]))
        timestamps.append(list(times[:head]))
        weights.append(list(wts[:head]))
        validation.append(
            HeldOut(user=user, item=seq[head], occurred_at=times[head], history=list(seq[:head]))
        )
        test.append(
            HeldOut(
                user=user,
                item=seq[head + 1],
                occurred_at=times[head + 1],
                # The test history includes the validation interaction. It is
                # not leakage: at serving time the model would have it, because
                # by then it is the past. Excluding it would make the offline
                # task harder than the real one and mis-state the model.
                history=list(seq[: head + 1]),
            )
        )

    train = Dataset(
        user_refs=list(dataset.user_refs),
        item_refs=list(dataset.item_refs),
        sequences=sequences,
        timestamps=timestamps,
        weights=weights,
        item_features=dataset.item_features,
        item_categories=dataset.item_categories,
        category_refs=list(dataset.category_refs),
    )
    return Split(train=train, validation=validation, test=test)


__all__ = ["MIN_INTERACTIONS", "HeldOut", "LeakageError", "Split", "leave_last_out"]
