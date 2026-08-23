"""The frozen dataset a run reads, and the count that decides a run may start.

A snapshot is the *inputs*, not the built `Dataset`. Interactions and product
rows go into the object; the `FeatureBuilder` is re-run over them at load. That
is deliberate and it is the difference between an artifact that can be
explained and one that can only be replayed: two runs over the same snapshot
with the same builder version produce the same indices, and if they do not, the
builder changed and the version number in the manifest says so. Serialising the
built `Dataset` instead would freeze a set of integer indices whose meaning
lives in code that has since moved on.

Everything here is `numpy`. Not `pickle` — ADR 0025's argument about checkpoints
applies unchanged to a snapshot: it is an artifact somebody could swap, and an
artifact that is also a program is a remote code execution waiting for an
operator to point it at the wrong bucket.

**`cutoff_at` is the point of the whole exercise.** Nine stages run over minutes
or hours and events keep arriving throughout. Without a fixed instant, the graph
would be built from one view of the table and the leave-last-out split from
another, and the held-out target could be an interaction that arrived *during*
training — leakage produced by wall-clock rather than by a bug in the split.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import sqlalchemy as sa

from graphrec.common.enums import Availability, EventType
from graphrec.ml.eval.split import MIN_INTERACTIONS
from graphrec.ml.features.builder import POSITIVE_EVENTS, Interaction, Product

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from graphrec.ml.features.builder import Dataset, FeatureBuilder

#: Bumped when the encoding changes shape. Read on decode and refused if it is
#: not this one: a snapshot written by a future version is not a snapshot this
#: version can honestly claim to have trained on.
FORMAT_VERSION = 1

#: The positive event types, as SQL sees them. Derived from the builder's own
#: set rather than retyped, because a fourth positive event added there and not
#: here would silently shrink every snapshot.
POSITIVE_EVENT_VALUES = tuple(sorted(event.value for event in POSITIVE_EVENTS))

#: Prices are `numeric(12,2)`; the feature builder buckets minor units.
MINOR_UNITS = 100

#: The sentinel for "this column was null". `-1` rather than NaN because the
#: columns it stands in for are integers, and a float array of prices would
#: reintroduce exactly the rounding the `numeric` column exists to avoid.
ABSENT = -1


@dataclass(frozen=True, slots=True)
class SnapshotContents:
    """Everything one run reads, and the instant it was true at."""

    cutoff_at: dt.datetime
    window_days: int
    interactions: list[Interaction]
    products: list[Product]

    @property
    def event_count(self) -> int:
        return len(self.interactions)

    @property
    def product_count(self) -> int:
        return len(self.products)

    def sequence_count(self) -> int:
        """Users with enough history to be split, which is what
        `training_min_sequences` counts and what L697 refuses on.

        `MIN_INTERACTIONS` is the split's threshold, imported rather than
        repeated: a snapshot that passes admission and then yields an empty
        validation set would be a job that fails after being told it could
        start.
        """
        per_user: dict[str, int] = {}
        for interaction in self.interactions:
            if interaction.event_type in POSITIVE_EVENTS:
                per_user[interaction.user_ref] = per_user.get(interaction.user_ref, 0) + 1
        return sum(1 for count in per_user.values() if count >= MIN_INTERACTIONS)

    def build(self, builder: FeatureBuilder) -> Dataset:
        return builder.build(self.interactions, self.products, reference_time=self.cutoff_at)


def window_start(cutoff_at: dt.datetime, window_days: int) -> dt.datetime:
    return cutoff_at - dt.timedelta(days=window_days)


async def count_eligible_sequences(
    session: AsyncSession, *, cutoff_at: dt.datetime, window_days: int
) -> int:
    """How many trainable sequences the tenant has, without reading any of them.

    The eligibility endpoint calls this on every page load of `/training`, so it
    is one aggregate over an index rather than a materialisation of the
    snapshot. The number it returns is the same number admission refuses on,
    computed the same way — a stat card that disagreed with the check behind the
    button would be worse than no stat card.
    """
    since = window_start(cutoff_at, window_days)
    count = await session.scalar(
        sa.text(
            "SELECT count(*) FROM ("
            "  SELECT customer_id FROM interaction_events"
            "   WHERE occurred_at >= :since AND occurred_at < :cutoff"
            "     AND event_type = ANY(:types)"
            "   GROUP BY customer_id"
            "  HAVING count(*) >= :minimum"
            ") AS eligible"
        ).bindparams(
            sa.bindparam("types", value=list(POSITIVE_EVENT_VALUES), type_=sa.ARRAY(sa.Text)),
        ),
        {"since": since, "cutoff": cutoff_at, "minimum": MIN_INTERACTIONS},
    )
    return int(count or 0)


async def read_contents(
    session: AsyncSession, *, cutoff_at: dt.datetime, window_days: int
) -> SnapshotContents:
    """Materialise the window under the tenant's own policy.

    Every event type is read, not just the positive ones: `remove_from_cart`
    carries a negative weight in `EVENT_WEIGHTS` and dropping it here would
    quietly change what the model is trained on.

    The whole catalogue is read, not only the eligible part of it. A product
    that is out of stock today still carries the signal of everyone who bought
    it last month, and it may be back tomorrow; eligibility is a *serving*
    filter (Phase 11) applied to candidates, not a training filter applied to
    history. Deleted products are the exception — `deleted_at` is retention or
    tenant deletion, and keeping a copy of the row in a snapshot would outlive
    the deletion that removed it.
    """
    since = window_start(cutoff_at, window_days)
    event_rows = (
        await session.execute(
            sa.text(
                "SELECT c.external_customer_id, p.external_product_id, e.event_type, e.occurred_at "
                "  FROM interaction_events AS e "
                "  JOIN customers AS c ON c.customer_id = e.customer_id "
                "  JOIN products AS p ON p.product_id = e.product_id "
                " WHERE e.occurred_at >= :since AND e.occurred_at < :cutoff "
                "   AND p.deleted_at IS NULL "
                " ORDER BY e.occurred_at, e.event_id"
            ),
            {"since": since, "cutoff": cutoff_at},
        )
    ).all()

    product_rows = (
        await session.execute(
            sa.text(
                "SELECT p.external_product_id, c.external_category_id, p.price, "
                "       p.availability, p.updated_at "
                "  FROM products AS p "
                "  LEFT JOIN product_categories AS c ON c.category_id = p.category_id "
                " WHERE p.deleted_at IS NULL "
                " ORDER BY p.external_product_id"
            )
        )
    ).all()

    interactions = [
        Interaction(
            user_ref=row[0],
            item_ref=row[1],
            event_type=EventType(row[2]),
            occurred_at=row[3],
        )
        for row in event_rows
    ]
    products = [
        Product(
            external_id=row[0],
            category=row[1],
            price_minor=None if row[2] is None else int(row[2] * MINOR_UNITS),
            availability=Availability(row[3]),
            updated_at=row[4],
        )
        for row in product_rows
    ]
    return SnapshotContents(
        cutoff_at=cutoff_at,
        window_days=window_days,
        interactions=interactions,
        products=products,
    )


def encode(contents: SnapshotContents) -> bytes:
    """`.npz`, with a JSON header for the scalars.

    Timestamps travel as microseconds since the epoch in `int64`. Not as
    `datetime64`, which `savez` stores happily and reads back without a time
    zone, and not as ISO strings, which would triple the size of the largest
    array in the file.
    """
    header = {
        "format_version": FORMAT_VERSION,
        "cutoff_at": contents.cutoff_at.isoformat(),
        "window_days": contents.window_days,
    }
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer,
        header=np.array(json.dumps(header)),
        user_ref=np.array([i.user_ref for i in contents.interactions], dtype=np.str_),
        item_ref=np.array([i.item_ref for i in contents.interactions], dtype=np.str_),
        event_type=np.array([i.event_type.value for i in contents.interactions], dtype=np.str_),
        occurred_at=np.array(
            [_micros(i.occurred_at) for i in contents.interactions], dtype=np.int64
        ),
        product_ref=np.array([p.external_id for p in contents.products], dtype=np.str_),
        product_category=np.array(
            [p.category if p.category is not None else "" for p in contents.products], dtype=np.str_
        ),
        product_has_category=np.array(
            [p.category is not None for p in contents.products], dtype=np.bool_
        ),
        product_price_minor=np.array(
            [ABSENT if p.price_minor is None else p.price_minor for p in contents.products],
            dtype=np.int64,
        ),
        product_availability=np.array(
            [p.availability.value for p in contents.products], dtype=np.str_
        ),
        product_updated_at=np.array(
            [ABSENT if p.updated_at is None else _micros(p.updated_at) for p in contents.products],
            dtype=np.int64,
        ),
    )
    return buffer.getvalue()


def decode(payload: bytes) -> SnapshotContents:
    """The inverse, refusing anything this version did not write.

    `allow_pickle` is left at its default of `False`. That default is the whole
    reason this format was chosen, and passing `True` for convenience would
    convert a data file back into a program.
    """
    with np.load(io.BytesIO(payload)) as archive:
        header = json.loads(str(archive["header"]))
        version = int(header.get("format_version", 0))
        if version != FORMAT_VERSION:
            raise ValueError(f"snapshot format {version} is not {FORMAT_VERSION}")

        interactions = [
            Interaction(
                user_ref=str(user),
                item_ref=str(item),
                event_type=EventType(str(event)),
                occurred_at=_instant(int(when)),
            )
            for user, item, event, when in zip(
                archive["user_ref"],
                archive["item_ref"],
                archive["event_type"],
                archive["occurred_at"],
                strict=True,
            )
        ]
        products = [
            Product(
                external_id=str(ref),
                category=str(category) if bool(has_category) else None,
                price_minor=None if int(price) == ABSENT else int(price),
                availability=Availability(str(availability)),
                updated_at=None if int(updated) == ABSENT else _instant(int(updated)),
            )
            for ref, category, has_category, price, availability, updated in zip(
                archive["product_ref"],
                archive["product_category"],
                archive["product_has_category"],
                archive["product_price_minor"],
                archive["product_availability"],
                archive["product_updated_at"],
                strict=True,
            )
        ]

    return SnapshotContents(
        cutoff_at=dt.datetime.fromisoformat(header["cutoff_at"]),
        window_days=int(header["window_days"]),
        interactions=interactions,
        products=products,
    )


def _micros(moment: dt.datetime) -> int:
    return int(moment.astimezone(dt.UTC).timestamp() * 1_000_000)


def _instant(micros: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(micros / 1_000_000, tz=dt.UTC)


__all__ = [
    "ABSENT",
    "FORMAT_VERSION",
    "POSITIVE_EVENT_VALUES",
    "SnapshotContents",
    "count_eligible_sequences",
    "decode",
    "encode",
    "read_contents",
    "window_start",
]
