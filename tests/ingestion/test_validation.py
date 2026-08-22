"""The item validator — one shape, one verdict, no message.

These run without a database. That is the point of `validation.py` being a pure
function of an item: the rules that decide whether a tenant's row is usable are
the rules most worth testing exhaustively, and they should not need Postgres to
be exercised.

A rejection names a **code**. Every assertion below checks the code, never a
sentence, because the sentence lives in `ITEM_ERROR_COPY` and is the console's
to render.
"""

from __future__ import annotations

import datetime as dt

import pytest

from graphrec.common.error_copy import ITEM_ERROR_COPY, resolve_item_copy
from graphrec.domain.ingestion.validation import (
    MAX_CLOCK_SKEW,
    MAX_EXTERNAL_ID_LENGTH,
    ItemInvalid,
    normalise_event,
    normalise_product,
    parse_timestamp,
    reference_for,
)

NOW = dt.datetime(2026, 8, 14, 9, 41, 2, tzinfo=dt.UTC)


def _event(**overrides):
    """The prototype's own snippet (dc.html L1176), field for field."""
    base = {
        "event_id": "ev-33810",
        "customer_id": "cus-9931",
        "external_product_id": "SKU-6002",
        "event_type": "purchase",
        "occurred_at": "2026-08-14T09:41:02Z",
        "value": "129.00",
        "context": {"surface": "product_page"},
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not ...}


def _product(**overrides):
    """The prototype's own snippet (L1173), field for field."""
    base = {
        "external_id": "SKU-4471",
        "title": "Brass hinge, 75mm",
        "category": "Hardware",
        "brand": "Northgate",
        "price": "8.40",
        "active": True,
        "availability": "in_stock",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not ...}


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(ItemInvalid) as caught:
        fn(*args, **kwargs)
    return caught.value.code


# ------------------------------------------------------------------- events


def test_the_prototypes_event_snippet_validates() -> None:
    item = normalise_event(_event(), now=NOW)
    assert item["external_event_id"] == "ev-33810"
    assert item["event_type"] == "purchase"
    assert item["context"] == {"surface": "product_page"}


def test_value_survives_as_a_string_not_a_float() -> None:
    """`129.00` through JSONB as a float is `129.0`, and then it is money lost.

    The staged item round-trips through `jsonb`, so a `Decimal` would be
    serialised as a float and come back with a different value. The validator
    therefore keeps the exact digits the tenant sent and defers the conversion
    to the merge, which writes into `numeric`.
    """
    item = normalise_event(_event(value="129.00"), now=NOW)
    assert item["value"] == "129.00"
    assert isinstance(item["value"], str)


def test_more_than_two_decimal_places_is_refused_not_rounded() -> None:
    """Silently rounding a tenant's money is worse than refusing it."""
    assert _code(normalise_event, _event(value="129.005"), now=NOW) == "item_value_not_decimal"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("event_id", ..., "item_event_id_missing"),
        ("event_id", "", "item_event_id_missing"),
        ("event_id", "x" * (MAX_EXTERNAL_ID_LENGTH + 1), "item_event_id_too_long"),
        ("customer_id", ..., "item_customer_id_missing"),
        ("external_product_id", ..., "item_product_id_missing"),
        ("event_type", "wishlist", "item_event_type_unknown"),
        ("occurred_at", ..., "item_occurred_at_missing"),
        ("occurred_at", "yesterday", "item_occurred_at_invalid"),
        ("context", ["not", "an", "object"], "item_context_not_an_object"),
    ],
)
def test_each_event_defect_names_its_own_code(field, value, code) -> None:
    assert _code(normalise_event, _event(**{field: value}), now=NOW) == code


def test_the_four_event_types_are_exactly_the_prototypes(monkeypatch) -> None:
    """L1369's control offers four, so four is the vocabulary."""
    for event_type in ("view", "add_to_cart", "purchase", "remove_from_cart"):
        assert normalise_event(_event(event_type=event_type), now=NOW)["event_type"] == event_type


def test_a_future_timestamp_is_refused_with_the_prototypes_own_reason() -> None:
    """L1180 publishes "occurred_at is in the future" as a sample reason."""
    ahead = NOW + MAX_CLOCK_SKEW + dt.timedelta(seconds=1)
    code = _code(normalise_event, _event(occurred_at=ahead.isoformat()), now=NOW)
    assert code == "item_occurred_at_in_future"
    assert resolve_item_copy(code) == "occurred_at is in the future"


def test_a_clock_a_little_ahead_is_tolerated() -> None:
    """A caller's clock is not a caller's fault.

    Without a tolerance, every integration whose server drifts by a few seconds
    would see intermittent per-item failures that no amount of correct code on
    their side could fix.
    """
    ahead = NOW + MAX_CLOCK_SKEW - dt.timedelta(seconds=1)
    assert normalise_event(_event(occurred_at=ahead.isoformat()), now=NOW)


def test_a_naive_timestamp_is_refused() -> None:
    """ "2026-08-14T09:41:02" without a zone is an hour nobody can name.

    Assuming UTC would silently shift every event from a tenant in another zone,
    and the shift would only ever be visible as slightly wrong recommendations.
    """
    with pytest.raises(ItemInvalid):
        parse_timestamp("2026-08-14T09:41:02")


def test_a_timestamp_is_normalised_to_utc() -> None:
    assert parse_timestamp("2026-08-14T11:41:02+02:00") == NOW


# ----------------------------------------------------------------- products


def test_the_prototypes_product_snippet_validates() -> None:
    item = normalise_product(_product())
    assert item["external_product_id"] == "SKU-4471"
    assert item["price"] == "8.40"
    assert item["is_active"] is True


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("external_id", ..., "item_external_id_missing"),
        ("title", ..., "item_title_missing"),
        ("title", "", "item_title_missing"),
        ("price", "-1.00", "item_price_not_positive_decimal"),
        ("price", "eight forty", "item_price_not_positive_decimal"),
        ("category", "c" * 121, "item_category_too_long"),
        ("availability", "backordered", "item_availability_unknown"),
        ("attributes", [1, 2], "item_attributes_not_object"),
    ],
)
def test_each_product_defect_names_its_own_code(field, value, code) -> None:
    assert _code(normalise_product, _product(**{field: value})) == code


def test_the_two_published_product_reasons_are_verbatim() -> None:
    """L1614's error rows are approved copy, not paraphrasable."""
    assert resolve_item_copy("item_price_not_positive_decimal") == "price is not a positive decimal"
    assert resolve_item_copy("item_category_too_long") == "category exceeds 120 characters"


def test_an_item_that_is_not_an_object_is_one_failure_not_a_crash() -> None:
    """A collection is `list[Any]`. A tenant may put a string in it."""
    assert _code(normalise_product, "SKU-4471") == "item_not_an_object"
    assert _code(normalise_event, None, now=NOW) == "item_not_an_object"


# --------------------------------------------------------------- references


def test_a_reference_prefers_the_identifier_the_tenant_sent() -> None:
    assert reference_for(_product(), ordinal=7, id_field="external_id") == "SKU-4471"


def test_a_missing_product_identifier_is_not_reported_as_an_unknown_one() -> None:
    """Two different failures, and a tenant fixes them in two different places.

    "unknown external product identifier" (L1629) is the catalog's verdict on an
    identifier that *was* sent. An item that sent none has a defect in the
    exporter that produced it, and telling the tenant to check their catalog
    would send them to the wrong system.
    """
    assert _code(normalise_event, _event(external_product_id=...), now=NOW) == (
        "item_product_id_missing"
    )
    assert resolve_item_copy("item_unknown_product") == "unknown external product identifier"
    assert resolve_item_copy("item_product_id_missing") == "product identifier is missing"


def test_a_reference_falls_back_to_the_position_when_there_is_no_identifier() -> None:
    """An item with no usable identifier still has to be findable in the file.

    "Errors identify the offending item" (L1391) — and for an item whose whole
    problem is that it has no identifier, the position is the only honest
    answer.
    """
    # One-based: the tenant is counting rows in a file, not indexing an array.
    reference = reference_for({"title": "Brass hinge"}, ordinal=7, id_field="external_id")
    assert reference == "item 8"


def test_a_reference_never_carries_the_items_contents() -> None:
    """NR-NF-06 — "Raw payloads are never echoed back." (L1391)"""
    secret = "hunter2-should-never-be-echoed"
    reference = reference_for({"password": secret}, ordinal=3, id_field="external_id")
    assert secret not in reference


# ---------------------------------------------------------------- copy cover


def test_every_code_the_validator_can_raise_has_approved_copy() -> None:
    """A missing entry is a `KeyError` at merge time, in a worker, at 3am.

    `resolve_item_copy` is fatal on a miss by design — a submission error row
    with an empty reason is worse than a loud failure. This test is what makes
    that design safe to hold.
    """
    raisers = [
        (
            normalise_event,
            {"now": NOW},
            _event,
            [
                ("event_id", ...),
                ("event_id", "x" * 200),
                ("customer_id", ...),
                ("customer_id", "x" * 200),
                ("external_product_id", ...),
                ("external_product_id", "x" * 200),
                ("event_type", "wishlist"),
                ("occurred_at", ...),
                ("occurred_at", "yesterday"),
                ("occurred_at", (NOW + dt.timedelta(days=1)).isoformat()),
                ("value", "1.0005"),
                ("context", [1]),
            ],
        ),
        (
            normalise_product,
            {},
            _product,
            [
                ("external_id", ...),
                ("external_id", "x" * 200),
                ("title", ...),
                ("title", "x" * 600),
                ("price", "-1"),
                ("category", "c" * 200),
                ("availability", "backordered"),
                ("attributes", [1]),
                ("description", "d" * 5_000),
            ],
        ),
    ]
    seen = set()
    for fn, kwargs, build, cases in raisers:
        for field, value in cases:
            seen.add(_code(fn, build(**{field: value}), **kwargs))
    seen.add(_code(normalise_product, "not an object"))

    missing = seen - set(ITEM_ERROR_COPY)
    assert not missing, f"no approved copy for {sorted(missing)}"
