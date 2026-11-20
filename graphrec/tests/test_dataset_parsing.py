from __future__ import annotations

import json

import pytest

from graphrec_core.datasets.service import _parse_dataset
from graphrec_core.errors import ApiError


def test_parse_json_object_with_products_and_events() -> None:
    raw = json.dumps(
        {
            "products": [{"external_id": "p-1", "title": "Widget"}],
            "events": [{"event_id": "e-1", "event_type": "view", "external_product_id": "p-1"}],
        }
    )
    products, events = _parse_dataset(raw)
    assert [p["external_id"] for p in products] == ["p-1"]
    assert [e["event_id"] for e in events] == ["e-1"]


def test_parse_json_array_splits_by_record_shape() -> None:
    raw = json.dumps(
        [
            {"external_id": "p-1", "title": "Widget"},
            {"event_id": "e-1", "event_type": "click"},
        ]
    )
    products, events = _parse_dataset(raw)
    assert len(products) == 1
    assert len(events) == 1


def test_parse_csv_events_with_json_context_column() -> None:
    raw = "event_id,event_type,user_id,context\ne-1,view,u-1,\"{\"\"page\"\": \"\"home\"\"}\"\n"
    products, events = _parse_dataset(raw)
    assert products == []
    assert events[0]["event_id"] == "e-1"
    assert events[0]["context"] == {"page": "home"}


def test_parse_csv_products_drops_blank_cells() -> None:
    raw = "external_id,title,category\np-1,Widget,\n"
    products, _ = _parse_dataset(raw)
    assert products == [{"external_id": "p-1", "title": "Widget"}]


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "{not json", "[1, 2]", json.dumps([{"title": "no identifier"}])],
)
def test_parse_rejects_malformed_payloads(raw: str) -> None:
    with pytest.raises(ApiError) as excinfo:
        _parse_dataset(raw)
    assert excinfo.value.status_code == 422
