"""Design test 1: the route table matches the schema.

Read from `frontend/openapi.json` rather than from a list maintained here. A
list would agree with the SDK by construction and disagree with the API in
silence; the schema is what the API actually publishes, and it is generated from
the FastAPI apps.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.sdk.conftest import CONTROL, DATA, KEY, Recorder, Reply, make_client
from tests.sdk.fixtures import ACCEPTED, FEEDBACK, RECEIPT, RECOMMENDATION, SUCCEEDED

ROOT = Path(__file__).resolve().parents[2]
SCHEMA: dict[str, Any] = json.loads((ROOT / "frontend" / "openapi.json").read_text())

#: `(namespace, method_name, kwargs, reply, expected origin, expected path)`.
#: The path is the OpenAPI template, so a concrete id is reversed back into its
#: slot below rather than compared as a string.
CALLS: list[tuple[str, str, dict[str, Any], Any, str, str]] = [
    (
        "catalog",
        "sync",
        {"sync_id": "s-1", "products": [{"external_id": "p-1", "title": "T"}]},
        ACCEPTED,
        CONTROL,
        "/v1/products:bulk-upsert",
    ),
    (
        "events",
        "submit",
        {
            "event_id": "e-1",
            "customer_id": "c-1",
            "external_product_id": "p-1",
            "event_type": "view",
            "occurred_at": datetime(2026, 8, 24, tzinfo=UTC),
        },
        RECEIPT,
        CONTROL,
        "/v1/events",
    ),
    (
        "events",
        "submit_batch",
        {
            "batch_id": "b-1",
            "events": [
                {
                    "event_id": "e-1",
                    "customer_id": "c-1",
                    "external_product_id": "p-1",
                    "event_type": "view",
                    "occurred_at": datetime(2026, 8, 24, tzinfo=UTC),
                }
            ],
        },
        ACCEPTED,
        CONTROL,
        "/v1/events/batches",
    ),
    (
        "submissions",
        "get_batch",
        {"batch_id": "b-1"},
        SUCCEEDED,
        CONTROL,
        "/v1/events/batches/{batch_id}",
    ),
    (
        "submissions",
        "get",
        {"submission_id": "sub-1"},
        SUCCEEDED,
        CONTROL,
        "/v1/submissions/{submission_id}",
    ),
    (
        "recommendations",
        "for_customer",
        {"request_id": "r-1", "customer_id": "c-1"},
        RECOMMENDATION,
        DATA,
        "/v1/recommendations",
    ),
    (
        "recommendations",
        "for_session",
        {"request_id": "r-1", "session_id": "s-1"},
        RECOMMENDATION,
        DATA,
        "/v1/recommendations/session",
    ),
    (
        "feedback",
        "impressions",
        {"request_id": "r-1", "events": [{"event_id": "e-1", "external_product_id": "p-1"}]},
        FEEDBACK,
        DATA,
        "/v1/feedback/impressions",
    ),
    (
        "feedback",
        "clicks",
        {"request_id": "r-1", "events": [{"event_id": "e-1", "external_product_id": "p-1"}]},
        FEEDBACK,
        DATA,
        "/v1/feedback/clicks",
    ),
    (
        "feedback",
        "conversions",
        {"request_id": "r-1", "events": [{"event_id": "e-1", "external_product_id": "p-1"}]},
        FEEDBACK,
        DATA,
        "/v1/feedback/conversions",
    ),
]


def _templated(path: str) -> str:
    """`/v1/submissions/sub-1` -> `/v1/submissions/{submission_id}`."""
    if path in SCHEMA["paths"]:
        return path
    for template in SCHEMA["paths"]:
        if "{" not in template:
            continue
        head, _, tail = template.partition("{")
        _, _, tail = tail.partition("}")
        if path.startswith(head) and path.endswith(tail) and len(path) > len(head) + len(tail):
            return template
    return path


def _drive(name: str, method: str, kwargs: dict[str, Any], reply: Any) -> Recorder:
    recorder = Recorder(replies=[Reply(status=200, body=reply)])
    with make_client(recorder) as client:
        getattr(getattr(client, name), method)(**kwargs)
    return recorder


@pytest.mark.parametrize(("name", "method", "kwargs", "reply", "origin", "path"), CALLS)
def test_call_hits_the_route_the_schema_publishes(
    name: str, method: str, kwargs: dict[str, Any], reply: Any, origin: str, path: str
) -> None:
    recorder = _drive(name, method, kwargs, reply)
    request = recorder.calls[0]
    assert f"{request.url.scheme}://{request.url.netloc.decode()}" == origin
    assert _templated(request.url.path) == path
    assert path in SCHEMA["paths"], f"{path} is not in the published schema"


def test_the_route_table_is_ten_rows() -> None:
    # A floor. Without it, an empty `CALLS` would make every parametrised
    # assertion above pass by not running.
    assert len(CALLS) == 10


def test_covers_every_data_plane_operation_in_the_schema() -> None:
    """No list to maintain: a route on the per-tenant host is a route a
    credential calls, so this fails the day the API grows one."""
    published = {
        path
        for path, operations in SCHEMA["paths"].items()
        for operation in operations.values()
        if isinstance(operation, dict)
        and "{tenant}" in ((operation.get("servers") or [{}])[0].get("url") or "")
    }
    covered = {path for *_, origin, path in CALLS if origin == DATA}
    assert published <= covered, f"uncovered data-plane routes: {published - covered}"


def test_sends_a_bearer_credential_and_nothing_else() -> None:
    """The credential contract on the wire, asserted from the client's side.

    `apps/inference/deps.py` reads `HTTPBearer`; the HMAC in
    `graphrec/auth/api_keys.py` is at-rest hashing on the server. So there is no
    signature to compute, no timestamp to send and no skew window — and a tenant
    header would be redundant with the hostname the request already went to.
    """
    recorder = _drive(
        "recommendations", "for_customer", {"request_id": "r", "customer_id": "c"}, RECOMMENDATION
    )
    headers = recorder.calls[0].headers
    assert headers["authorization"] == f"Bearer {KEY}"
    for absent in ("x-signature", "x-timestamp", "x-graphrec-tenant", "x-tenant-id"):
        assert absent not in headers


def test_does_not_send_an_idempotency_key_header_but_does_send_the_body_key() -> None:
    """`Idempotency-Key` is in the API's CORS allowlist and no handler reads it.

    The key is in the body — `batch_id` here — so sending the header would be
    advertising a guarantee the server does not make.
    """
    recorder = _drive(
        "events",
        "submit_batch",
        {
            "batch_id": "b-1",
            "events": [
                {
                    "event_id": "e-1",
                    "customer_id": "c-1",
                    "external_product_id": "p-1",
                    "event_type": "view",
                    "occurred_at": datetime(2026, 8, 24, tzinfo=UTC),
                }
            ],
        },
        ACCEPTED,
    )
    assert "idempotency-key" not in recorder.calls[0].headers
    assert recorder.bodies[0]["batch_id"] == "b-1"


# ------------------------------------------------------- fixtures vs. schema


def _deref(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not schema:
        return None
    ref = schema.get("$ref")
    if ref:
        return _deref(SCHEMA["components"]["schemas"][ref.split("/")[-1]])
    return schema


def _response_schema(method: str, path: str) -> dict[str, Any]:
    operation = SCHEMA["paths"][path][method.lower()]
    success = next(r for code, r in operation["responses"].items() if code.startswith("2"))
    resolved = _deref(success["content"]["application/json"]["schema"])
    assert resolved is not None
    return resolved


def _conforms(schema: dict[str, Any] | None, value: Any, where: str) -> None:
    resolved = _deref(schema)
    if resolved is None or value is None:
        return
    if isinstance(value, list):
        for index, entry in enumerate(value):
            _conforms(resolved.get("items"), entry, f"{where}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for required in resolved.get("required", []):
        assert required in value, f"{where}.{required} is missing from the fixture"
    for field, child in (resolved.get("properties") or {}).items():
        if field in value:
            branch = next((o for o in child.get("anyOf", []) if "$ref" in o), child)
            _conforms(branch, value[field], f"{where}.{field}")


@pytest.mark.parametrize(
    ("method", "path", "fixture"),
    [
        ("POST", "/v1/recommendations", RECOMMENDATION),
        ("POST", "/v1/feedback/impressions", FEEDBACK),
        ("POST", "/v1/events", RECEIPT),
        ("POST", "/v1/products:bulk-upsert", ACCEPTED),
        ("GET", "/v1/submissions/{submission_id}", SUCCEEDED),
    ],
)
def test_fixture_matches_the_published_response_schema(
    method: str, path: str, fixture: dict[str, Any]
) -> None:
    _conforms(_response_schema(method, path), fixture, path)
