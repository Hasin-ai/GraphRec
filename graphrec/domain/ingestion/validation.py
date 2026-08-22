"""Deciding whether one submitted item is usable, and saying why if it is not.

Two rules govern everything here.

**One validator per shape, used by every path.** The single-event route and the
batch worker call `normalise_event`; the product route's service and the bulk
worker agree on `normalise_product`. A batch that accepted an item the single
route would have refused — or the reverse — would make the two ways of sending
the same data mean different things.

**A rejection names a code, never a message.** `ItemInvalid` carries a code that
`ITEM_ERROR_COPY` resolves into the approved sentence at the point of storage.
Nothing in this module formats a reason, and nothing in it puts any part of the
submitted item into one: "Raw payloads are never echoed back" (dc.html L1391).

The one thing that *is* echoed is the item's own external identifier — the
prototype's error table is a list of them (`SKU-9004`, `ev-33810`, L689) and it
would be useless without. `reference_for` is where that is bounded: an
identifier that is not a short string is replaced with the item's position, so a
tenant cannot make us store an arbitrary blob by putting one in the id field.
"""

from __future__ import annotations

import datetime as dt
import decimal
from typing import Any

from graphrec.common.enums import Availability, EventType

#: Matches `ck_*_external_id_length` in migrations 0007 and 0008. Repeated
#: rather than imported because the check constraint is the authority and this
#: is the courtesy that keeps a tenant from finding out about it as a 500.
MAX_EXTERNAL_ID_LENGTH = 120
MAX_TITLE_LENGTH = 500
MAX_CATEGORY_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 4_000

#: How far ahead of our clock a tenant's clock may be before an event is
#: refused as future-dated. "occurred_at is in the future" (L1180) cannot mean
#: "later than this instant": a client whose clock is two seconds fast would
#: have every event rejected, and clock skew is not the tenant's fault.
MAX_CLOCK_SKEW = dt.timedelta(minutes=5)

_EVENT_TYPES = frozenset(t.value for t in EventType)
_AVAILABILITY = frozenset(a.value for a in Availability)


class ItemInvalid(Exception):  # noqa: N818 - a per-item verdict, not a request failure
    """One item cannot be used. Carries the code, not the sentence.

    Not a `GraphRecError`: an invalid item does not fail the request it arrived
    in. It becomes a row in `submission_errors` and the accepted remainder is
    applied around it — "Failures are reported per item; the accepted remainder
    is not discarded." (L1353)
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def reference_for(raw: Any, *, ordinal: int, id_field: str) -> str:
    """The identifier to report this item under, bounded.

    Falls back to the item's **one-based** position when there is no usable
    identifier, which is the only thing a tenant can act on for an item that
    failed *because* its identifier was missing. One-based because this string
    is read by a person counting rows in a file they exported; the zero-based
    index stays on `submission_errors.ordinal` for anything programmatic.
    """
    if isinstance(raw, dict):
        candidate = raw.get(id_field)
        if isinstance(candidate, str):
            trimmed = candidate.strip()
            if 0 < len(trimmed) <= MAX_EXTERNAL_ID_LENGTH:
                return trimmed
    return f"item {ordinal + 1}"


# ------------------------------------------------------------------- helpers


def _object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ItemInvalid("item_not_an_object")
    return raw


def _external_id(raw: dict[str, Any], field: str, *, missing: str, too_long: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ItemInvalid(missing)
    trimmed = value.strip()
    if len(trimmed) > MAX_EXTERNAL_ID_LENGTH:
        raise ItemInvalid(too_long)
    return trimmed


def _optional_text(raw: dict[str, Any], field: str, *, limit: int, too_long: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ItemInvalid(too_long)
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > limit:
        raise ItemInvalid(too_long)
    return trimmed


def _mapping(raw: dict[str, Any], field: str, *, code: str) -> dict[str, Any]:
    value = raw.get(field)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ItemInvalid(code)
    return value


def _decimal(value: Any, *, code: str) -> str | None:
    """A money amount, as a string.

    A string because the normalised item is stored as JSONB and then read back
    by the merge. `json` renders a `Decimal` as a float, and a price that has
    been through a float is a price that can be billed wrongly (BACKEND_PLAN
    §14). The database casts it back to `numeric` in the merge.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ItemInvalid(code)
    try:
        amount = decimal.Decimal(str(value))
    except (decimal.InvalidOperation, ValueError) as exc:
        raise ItemInvalid(code) from exc
    if not amount.is_finite() or amount < 0:
        raise ItemInvalid(code)
    if amount.as_tuple().exponent < -2:  # type: ignore[operator]
        # Silently rounding a tenant's money is worse than refusing it.
        raise ItemInvalid(code)
    return str(amount)


def parse_timestamp(value: Any) -> dt.datetime:
    """An RFC 3339 instant, always timezone-aware.

    A naive timestamp is refused rather than assumed to be UTC. "2026-08-14
    09:41" means different instants in different places, and guessing which one
    a tenant meant would silently reorder their event history.
    """
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ItemInvalid("item_occurred_at_invalid") from exc
    else:
        raise ItemInvalid("item_occurred_at_missing")
    if parsed.tzinfo is None:
        raise ItemInvalid("item_occurred_at_invalid")
    return parsed.astimezone(dt.UTC)


# -------------------------------------------------------------------- events


def normalise_event(raw: Any, *, now: dt.datetime) -> dict[str, Any]:
    """One interaction event, in the shape the merge reads.

    Returns JSON-safe primitives only: this goes into a JSONB staging row and
    comes back out through SQL, so a `Decimal` or a `datetime` here would be a
    float or a string with no timezone by the time the merge saw it.
    """
    item = _object(raw)
    external_event_id = _external_id(
        item, "event_id", missing="item_event_id_missing", too_long="item_event_id_too_long"
    )
    external_customer_id = _external_id(
        item,
        "customer_id",
        missing="item_customer_id_missing",
        too_long="item_customer_id_too_long",
    )
    external_product_id = _external_id(
        item,
        "external_product_id",
        # Not `item_unknown_product`: this pass has not looked in the catalog
        # and is in no position to say anything about what is in it. Whether
        # the identifier names a product is the merge's verdict, taken in SQL
        # against the tenant's own rows.
        missing="item_product_id_missing",
        too_long="item_product_id_too_long",
    )

    event_type = item.get("event_type")
    if not isinstance(event_type, str) or event_type not in _EVENT_TYPES:
        raise ItemInvalid("item_event_type_unknown")

    occurred_at = parse_timestamp(item.get("occurred_at"))
    if occurred_at > now + MAX_CLOCK_SKEW:
        raise ItemInvalid("item_occurred_at_in_future")

    return {
        "external_event_id": external_event_id,
        "external_customer_id": external_customer_id,
        "external_product_id": external_product_id,
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat(),
        "value": _decimal(item.get("value"), code="item_value_not_decimal"),
        "context": _mapping(item, "context", code="item_context_not_an_object"),
    }


# ------------------------------------------------------------------ products


def normalise_product(raw: Any) -> dict[str, Any]:
    """One catalogue entry from a synchronization, in the shape the merge reads.

    `active` and `availability` default rather than being required, because a
    synchronization is a statement of the catalogue's current contents: an item
    that says nothing about its availability is in stock, exactly as it would be
    through `POST /v1/products`.
    """
    item = _object(raw)
    external_product_id = _external_id(
        item,
        "external_id",
        missing="item_external_id_missing",
        too_long="item_external_id_too_long",
    )

    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ItemInvalid("item_title_missing")
    if len(title.strip()) > MAX_TITLE_LENGTH:
        raise ItemInvalid("item_title_too_long")

    availability = item.get("availability", Availability.IN_STOCK.value)
    if not isinstance(availability, str) or availability not in _AVAILABILITY:
        raise ItemInvalid("item_availability_unknown")

    active = item.get("active", True)
    if not isinstance(active, bool):
        raise ItemInvalid("item_not_an_object")

    return {
        "external_product_id": external_product_id,
        "title": title.strip(),
        "category": _optional_text(
            item, "category", limit=MAX_CATEGORY_LENGTH, too_long="item_category_too_long"
        ),
        "brand": _optional_text(
            item, "brand", limit=MAX_CATEGORY_LENGTH, too_long="item_category_too_long"
        ),
        "price": _decimal(item.get("price"), code="item_price_not_positive_decimal"),
        "is_active": active,
        "availability": availability,
        "description": _optional_text(
            item, "description", limit=MAX_DESCRIPTION_LENGTH, too_long="item_title_too_long"
        ),
        "attributes": _mapping(item, "attributes", code="item_attributes_not_object"),
    }


__all__ = [
    "MAX_CLOCK_SKEW",
    "MAX_EXTERNAL_ID_LENGTH",
    "ItemInvalid",
    "normalise_event",
    "normalise_product",
    "parse_timestamp",
    "reference_for",
]
