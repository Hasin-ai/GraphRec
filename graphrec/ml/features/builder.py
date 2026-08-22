"""`FeatureBuilder` — the one place raw rows become model input.

BACKEND_PLAN L1771 is emphatic that this module is "called by snapshot
generation, evaluation replay and inference alike", and the reason is the oldest
failure in applied recommendation: training computes a feature one way, serving
computes it another, and the model is quietly asked a question it was never
trained on. There is no second implementation of any of this — if serving needs
a price bucket it calls `FeatureBuilder`, and if `FeatureBuilder` changes, the
model that was trained against the old one is a different model.

Three properties are load-bearing.

**Determinism.** Index assignment is by first appearance in a deterministically
sorted stream, never by set iteration or dict insertion from an unordered query.
Two runs over the same rows produce the same integers, which is what makes a
checkpoint mean anything and what makes the seeded fixture reproducible.

**Purity.** Nothing here touches a database, a clock or a random number. It takes
rows and returns arrays. That is what lets the evaluator replay a snapshot and
the inference process rebuild a user's sequence from the same code.

**No leakage by construction.** `FeatureBuilder` orders interactions but never
truncates them; the train/test boundary is `graphrec.ml.eval.split`'s business
and is applied to the *dataset*, so a feature can never be computed from rows the
split has already set aside. The one exception is stated where it happens:
`item_popularity` is computed from whatever interactions it is handed, and the
evaluator must hand it training rows only.

Numpy, not torch. The feature builder runs in the inference process on the
request path, and it has no business allocating on a GPU to bucket a price.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from graphrec.common.enums import Availability, EventType

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from numpy.typing import NDArray

#: How much each event type says about intent. A purchase is the signal; a view
#: is weak evidence; a removal is the tenant telling us the earlier add was
#: wrong, so it is *negative* and the only weight below zero.
#:
#: These are training weights, not scores. They scale the BPR term for an
#: interaction, so a purchase moves the embedding further than a view does.
EVENT_WEIGHTS: Mapping[EventType, float] = {
    EventType.VIEW: 1.0,
    EventType.ADD_TO_CART: 3.0,
    EventType.PURCHASE: 5.0,
    EventType.REMOVE_FROM_CART: -2.0,
}

#: Interactions that express intent. `remove_from_cart` is excluded from the
#: sequence and from the graph: an edge whose meaning is "not this" is not an
#: edge a similarity model can use, and its weight is kept only so a future
#: negative-sampling policy can prefer it.
POSITIVE_EVENTS: frozenset[EventType] = frozenset(
    {EventType.VIEW, EventType.ADD_TO_CART, EventType.PURCHASE}
)

#: Price bands, in minor units, as upper bounds. Buckets rather than a raw price
#: because a tenant's currency and scale are theirs, and a model that learned an
#: absolute price would relearn nothing when a tenant repriced its catalogue.
#: The last bucket is unbounded.
PRICE_BUCKET_BOUNDS: tuple[int, ...] = (1_000, 5_000, 20_000, 100_000)

#: Number of static item feature columns: category one-hot is *not* one of them —
#: category arrives as an integer index for an embedding table. These are the
#: dense side: price bucket (normalised), availability (normalised), and a
#: recency figure.
STATIC_FEATURE_DIM = 3

#: A sequence longer than this is truncated from the *left*, keeping the most
#: recent interactions. CON-01's sequence pathway is about what a session is
#: doing now; a user's first hundred views a year ago are the graph's job.
MAX_SEQUENCE_LENGTH = 50


@dataclass(frozen=True, slots=True)
class Interaction:
    """One event, as the model sees it.

    External identifiers, not database rows: this type is what the snapshot
    reader, the fixture generator and the inference request all produce, and
    binding it to a SQLAlchemy row would make two of those three impossible.
    """

    user_ref: str
    item_ref: str
    event_type: EventType
    occurred_at: dt.datetime

    @property
    def weight(self) -> float:
        return EVENT_WEIGHTS[self.event_type]


@dataclass(frozen=True, slots=True)
class Product:
    """The catalogue side, reduced to what the model can use.

    `external_id` matches `Interaction.item_ref`. Everything else is optional,
    because a tenant may have merged a product with nothing but a title and the
    model still has to place it.
    """

    external_id: str
    category: str | None = None
    price_minor: int | None = None
    availability: Availability = Availability.IN_STOCK
    updated_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class Dataset:
    """The built artifact. Indices, sequences and features, all aligned.

    Everything is positional: `item_features[i]` describes the item whose index
    is `i`, `sequences[u]` belongs to the user whose index is `u`. The two
    `*_refs` lists are the way back out, and are what the candidate index and
    the API respond with — a model version that returned integers would be
    meaningless the moment the catalogue changed.
    """

    user_refs: list[str]
    item_refs: list[str]
    #: Per user, item indices in ascending time order. Positive events only.
    sequences: list[list[int]]
    #: Per user, the timestamp of each interaction in `sequences`, same shape.
    timestamps: list[list[dt.datetime]]
    #: Per user, the training weight of each interaction, same shape.
    weights: list[list[float]]
    #: `(n_items, STATIC_FEATURE_DIM)`, float32.
    item_features: NDArray[np.float32]
    #: `(n_items,)`, int64. Index 0 is reserved for "no category".
    item_categories: NDArray[np.int64]
    category_refs: list[str] = field(default_factory=list)

    @property
    def n_users(self) -> int:
        return len(self.user_refs)

    @property
    def n_items(self) -> int:
        return len(self.item_refs)

    @property
    def n_categories(self) -> int:
        """Includes the reserved 0."""
        return len(self.category_refs) + 1

    @property
    def n_interactions(self) -> int:
        return sum(len(seq) for seq in self.sequences)

    def user_index(self, ref: str) -> int | None:
        return self._user_lookup.get(ref)

    def item_index(self, ref: str) -> int | None:
        return self._item_lookup.get(ref)

    @property
    def _user_lookup(self) -> dict[str, int]:
        return {ref: i for i, ref in enumerate(self.user_refs)}

    @property
    def _item_lookup(self) -> dict[str, int]:
        return {ref: i for i, ref in enumerate(self.item_refs)}

    def item_popularity(self) -> NDArray[np.int64]:
        """Interaction count per item, over *this dataset's* rows.

        The evaluator must call this on the training split. Called on the full
        dataset it would count the held-out interaction it is about to predict,
        and the popularity baseline would beat the model by cheating.
        """
        counts = np.zeros(self.n_items, dtype=np.int64)
        for seq in self.sequences:
            for item in seq:
                counts[item] += 1
        return counts


class FeatureBuilder:
    """Rows in, `Dataset` out.

    Stateless between calls and configured only by the constants above, so two
    builders constructed anywhere in the system agree. It is a class rather than
    a function because Phase 10's bundle manifest records the feature version,
    and a version belongs to an object that can report it.
    """

    #: Bumped whenever the meaning of a produced feature changes. The bundle
    #: manifest carries it, and inference refuses a bundle built by a different
    #: one — a model trained against v1 features fed v2 features is not a
    #: degraded model, it is a wrong one.
    VERSION = 1

    def __init__(self, *, max_sequence_length: int = MAX_SEQUENCE_LENGTH) -> None:
        self.max_sequence_length = max_sequence_length

    def build(
        self,
        interactions: Iterable[Interaction],
        products: Iterable[Product] = (),
        *,
        reference_time: dt.datetime | None = None,
    ) -> Dataset:
        """Build the dataset.

        `reference_time` anchors the recency feature. It is a parameter and not
        `utcnow()` on purpose: a snapshot evaluated a week after it was built
        must produce the same features it produced when it was built, and a
        builder that read the clock would make every replay a different dataset.
        Defaults to the latest interaction, which is the snapshot's own horizon.
        """
        rows = sorted(
            (i for i in interactions if i.event_type in POSITIVE_EVENTS),
            key=_ordering_key,
        )

        catalogue = {p.external_id: p for p in products}

        # Items are indexed from the catalogue first, in sorted reference order,
        # so that a product with no interactions still has an index and can be
        # recommended. Cold-start items are the point of having a graph.
        item_refs: list[str] = sorted(catalogue)
        item_lookup = {ref: i for i, ref in enumerate(item_refs)}
        for row in rows:
            if row.item_ref not in item_lookup:
                item_lookup[row.item_ref] = len(item_refs)
                item_refs.append(row.item_ref)

        user_refs: list[str] = []
        user_lookup: dict[str, int] = {}
        sequences: list[list[int]] = []
        timestamps: list[list[dt.datetime]] = []
        weights: list[list[float]] = []

        for row in rows:
            user = user_lookup.get(row.user_ref)
            if user is None:
                user = len(user_refs)
                user_lookup[row.user_ref] = user
                user_refs.append(row.user_ref)
                sequences.append([])
                timestamps.append([])
                weights.append([])
            sequences[user].append(item_lookup[row.item_ref])
            timestamps[user].append(row.occurred_at)
            weights[user].append(row.weight)

        if reference_time is None:
            reference_time = max(
                (row.occurred_at for row in rows), default=dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
            )

        features, categories, category_refs = self._item_matrix(
            item_refs, catalogue, reference_time=reference_time
        )

        return Dataset(
            user_refs=user_refs,
            item_refs=item_refs,
            sequences=sequences,
            timestamps=timestamps,
            weights=weights,
            item_features=features,
            item_categories=categories,
            category_refs=category_refs,
        )

    def recent(self, sequence: Sequence[int]) -> list[int]:
        """The tail the sequence pathway is given.

        Public because inference calls it directly on a live session, and the
        truncation rule has to be the same one training used.
        """
        return list(sequence[-self.max_sequence_length :])

    def _item_matrix(
        self,
        item_refs: Sequence[str],
        catalogue: Mapping[str, Product],
        *,
        reference_time: dt.datetime,
    ) -> tuple[NDArray[np.float32], NDArray[np.int64], list[str]]:
        category_refs = sorted({p.category for p in catalogue.values() if p.category})
        category_lookup = {ref: i + 1 for i, ref in enumerate(category_refs)}

        features = np.zeros((len(item_refs), STATIC_FEATURE_DIM), dtype=np.float32)
        categories = np.zeros(len(item_refs), dtype=np.int64)

        for i, ref in enumerate(item_refs):
            product = catalogue.get(ref)
            if product is None:
                # An interaction against an unmerged product. Zeroed features
                # and the reserved category, which is a truthful "we know
                # nothing about this item" rather than an invented average.
                continue
            features[i, 0] = _price_bucket(product.price_minor) / len(PRICE_BUCKET_BOUNDS)
            features[i, 1] = _availability_score(product.availability)
            features[i, 2] = _recency(product.updated_at, reference_time)
            categories[i] = category_lookup.get(product.category or "", 0)

        return features, categories, category_refs


def _ordering_key(row: Interaction) -> tuple[dt.datetime, str, str, str]:
    """Time first, then references, so simultaneous events order the same way
    on every run. Events arriving in the same millisecond are common in a batch
    import, and leaving their order to the query planner would make index
    assignment — and therefore a checkpoint — irreproducible."""
    return (row.occurred_at, row.user_ref, row.item_ref, row.event_type.value)


def _price_bucket(price_minor: int | None) -> int:
    """`0..len(PRICE_BUCKET_BOUNDS)`. An unknown price lands in the lowest
    bucket, which is stated here rather than hidden: the alternative is a
    separate "unknown" column, and three static features already carry more
    weight than a catalogue this sparse can justify."""
    if price_minor is None:
        return 0
    return sum(1 for bound in PRICE_BUCKET_BOUNDS if price_minor >= bound)


def _availability_score(availability: Availability) -> float:
    """In stock is 1, out of stock is 0, low stock sits between.

    Ordinal rather than one-hot because the ordering is real — a low-stock item
    is a worse recommendation than an in-stock one and a better one than
    something nobody can buy — and the funnel in Phase 11 filters on the same
    ordering.
    """
    return {
        Availability.IN_STOCK: 1.0,
        Availability.LOW_STOCK: 0.5,
        Availability.OUT_OF_STOCK: 0.0,
    }[availability]


def _recency(updated_at: dt.datetime | None, reference_time: dt.datetime) -> float:
    """Exponential decay over 30 days, in `[0, 1]`.

    Decay rather than a raw age so that the feature saturates: the difference
    between a product touched yesterday and one touched today should matter, and
    the difference between two years and three should not.
    """
    if updated_at is None:
        return 0.0
    age_days = max((reference_time - updated_at).total_seconds(), 0.0) / 86_400.0
    return float(np.exp(-age_days / 30.0))


__all__ = [
    "EVENT_WEIGHTS",
    "MAX_SEQUENCE_LENGTH",
    "POSITIVE_EVENTS",
    "PRICE_BUCKET_BOUNDS",
    "STATIC_FEATURE_DIM",
    "Dataset",
    "FeatureBuilder",
    "Interaction",
    "Product",
]
