"""A synthetic tenant, generated from a seed, with a signal worth learning.

Phase 8 has to be provable before there is a database, a job queue or a tenant,
so it needs data. Real data is not available and a random one would be worse
than none: if interactions are uniform noise then no model can beat popularity,
the exit criterion becomes unmeetable, and the only way to pass is to weaken it.

So the fixture has **structure that popularity cannot capture and the model can**:
every user has a latent preferred category, and 85% of their interactions fall
inside it. Within a category the choice is Zipf-skewed, and — this is the part
that makes the fixture honest — *the same* skew shape is used in every category,
so global popularity carries no information about which category a given user
wants. A popularity ranker sees four interchangeable heads and must spread its
ten slots across all of them; a model that has learned the user's category can
spend all ten inside it. The gap between those two is exactly the personalisation
the system claims to sell, and it is the gap the exit criterion measures.

**Each user's items are distinct.** A real stream repeats — people view the same
product four times — but both the evaluator and Phase 11's funnel exclude items
the user has already interacted with, so a repeat-heavy corpus caps Recall@10 at
the non-repeat rate and the metric ends up measuring the protocol instead of the
model. The repeat case belongs in a serving test, where the funnel is the thing
under test; here it would only lower the ceiling for both sides equally and make
the comparison harder to read.

Everything is a pure function of `seed`. `numpy.random.default_rng(seed)` and
nothing else — no `random`, no clock, no `uuid4`. Two calls with the same seed
produce byte-identical interactions, which is what lets a metric regression be
attributed to a code change rather than to the data moving underneath it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from graphrec.common.enums import Availability, EventType
from graphrec.ml.features.builder import Interaction, Product

#: The fixture's epoch. Fixed rather than `utcnow()`, so a temporal split run
#: today and run next year partition the same interactions the same way.
EPOCH = dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.UTC)

#: Probability an interaction comes from the user's preferred category.
#: Below about 0.7 the signal is too weak for a small fixture to learn in the
#: seconds a test may take; at 1.0 the task is trivial and the metric stops
#: distinguishing a working model from a lucky one.
AFFINITY = 0.85

#: Zipf exponent inside a category. Identical across categories on purpose —
#: see the module docstring.
ZIPF = 0.8

#: Event mix. Mostly views, because that is what a real stream is, and because a
#: fixture where every event is a purchase would never exercise the weighting.
EVENT_MIX: tuple[tuple[EventType, float], ...] = (
    (EventType.VIEW, 0.70),
    (EventType.ADD_TO_CART, 0.20),
    (EventType.PURCHASE, 0.08),
    (EventType.REMOVE_FROM_CART, 0.02),
)


@dataclass(frozen=True, slots=True)
class SyntheticTenant:
    """The generated corpus, plus the ground truth used only for diagnosis.

    `preferences` is *not* a feature. It is the latent variable the generator
    used, kept so a test can say "the model recovered the structure" rather than
    only "the number went up", and so a failing run can be diagnosed without
    re-deriving what the data was supposed to contain.
    """

    interactions: list[Interaction]
    products: list[Product]
    preferences: dict[str, int]
    n_categories: int

    @property
    def n_users(self) -> int:
        return len(self.preferences)


def generate(
    *,
    seed: int = 20260101,
    n_users: int = 160,
    n_categories: int = 5,
    items_per_category: int = 20,
    min_interactions: int = 8,
    max_interactions: int = 15,
) -> SyntheticTenant:
    """Build a deterministic tenant.

    The defaults are chosen so the task has a known ceiling. A user ends up
    having seen roughly half of their preferred category, leaving about nine
    unseen items in it — which fits inside a top-10 list. The best achievable
    Recall@10 is therefore close to `AFFINITY`, and the exit criterion can be
    judged against an upper bound rather than against a number nobody can say is
    good.
    """
    rng = np.random.default_rng(seed)
    n_items = n_categories * items_per_category

    products = [
        Product(
            external_id=_item_ref(index),
            category=f"cat-{index // items_per_category}",
            # Prices span all four buckets so the static feature has variance;
            # a constant column would train a dead weight and hide a bug in the
            # projection layer.
            price_minor=int(rng.integers(200, 200_000)),
            availability=_availability(rng),
            updated_at=EPOCH - dt.timedelta(days=int(rng.integers(0, 120))),
        )
        for index in range(n_items)
    ]

    # One Zipf profile, reused per category, so global popularity is flat across
    # categories and the baseline gets no free category signal.
    ranks = np.arange(1, items_per_category + 1, dtype=np.float64)
    within = ranks ** (-ZIPF)
    within = within / within.sum()

    event_types = [event for event, _ in EVENT_MIX]
    event_p = np.array([weight for _, weight in EVENT_MIX], dtype=np.float64)
    event_p = event_p / event_p.sum()

    interactions: list[Interaction] = []
    preferences: dict[str, int] = {}

    for user in range(n_users):
        user_ref = f"user-{user:04d}"
        preferred = int(rng.integers(0, n_categories))
        preferences[user_ref] = preferred

        count = int(rng.integers(min_interactions, max_interactions + 1))

        # The user's basket: `count` distinct items, drawn without replacement
        # from a mixture that puts `AFFINITY` of its mass on their category and
        # spreads the rest evenly over the others.
        chosen = rng.choice(
            n_items,
            size=count,
            replace=False,
            p=_mixture(
                preferred, within, n_categories=n_categories, items_per_category=items_per_category
            ),
        )

        # Then permuted, so the *temporal* order is independent of how likely
        # each item was. Without this the without-replacement draw would put the
        # popular items first and the held-out last interaction would
        # systematically be the user's least popular item — which would make the
        # popularity baseline look worse than it is and the comparison
        # meaningless.
        chosen = rng.permutation(chosen)

        # Each user's clock starts somewhere in the first ninety days and
        # advances by hours, so the global stream interleaves users rather than
        # emitting one user's whole history before the next begins. A split that
        # only ever saw blocked-by-user data would not exercise the ordering.
        moment = EPOCH + dt.timedelta(hours=float(rng.integers(0, 90 * 24)))

        for item in chosen:
            interactions.append(
                Interaction(
                    user_ref=user_ref,
                    item_ref=_item_ref(int(item)),
                    event_type=event_types[int(rng.choice(len(event_types), p=event_p))],
                    occurred_at=moment,
                )
            )
            moment += dt.timedelta(hours=float(rng.integers(1, 72)))

    # Sorted by time so the corpus reads like a stream. `FeatureBuilder` sorts
    # again anyway; emitting it sorted means a caller that skips the builder —
    # a fixture inspected by hand, say — still sees the right thing.
    interactions.sort(key=lambda row: (row.occurred_at, row.user_ref, row.item_ref))
    return SyntheticTenant(
        interactions=interactions,
        products=products,
        preferences=preferences,
        n_categories=n_categories,
    )


def _mixture(
    preferred: int,
    within: np.ndarray,
    *,
    n_categories: int,
    items_per_category: int,
) -> np.ndarray:
    """The user's item distribution: `AFFINITY` inside their category, the rest
    spread evenly over the others, and `within` applied identically inside each.

    Identically is the load-bearing word — see the module docstring. Global
    popularity therefore carries no category signal at all, and anything the
    model gains over the baseline is personalisation rather than a head it
    happened to memorise.
    """
    other = (1.0 - AFFINITY) / max(n_categories - 1, 1)
    weights = np.empty(n_categories * items_per_category, dtype=np.float64)
    for category in range(n_categories):
        share = AFFINITY if category == preferred else other
        start = category * items_per_category
        weights[start : start + items_per_category] = share * within
    return weights / weights.sum()


def _item_ref(index: int) -> str:
    return f"SKU-{index:04d}"


def _availability(rng: np.random.Generator) -> Availability:
    """Mostly in stock, with enough of the other two that the funnel's
    out-of-stock filter in Phase 11 has something to remove."""
    draw = rng.random()
    if draw < 0.80:
        return Availability.IN_STOCK
    if draw < 0.93:
        return Availability.LOW_STOCK
    return Availability.OUT_OF_STOCK


__all__ = ["AFFINITY", "EPOCH", "EVENT_MIX", "ZIPF", "SyntheticTenant", "generate"]
