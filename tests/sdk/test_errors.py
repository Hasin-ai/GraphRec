"""Design test 3: every error the server can send becomes a typed error here.

The mapping is driven off the server's own source rather than off a list copied
into this file, because a list copied into this file is a list that stops being
true the first time somebody adds a class. `ErrorClass` is read out of
`graphrec/common/errors.py` and every member must resolve to something more
specific than the base class; the code table is read out of
`graphrec/common/error_copy.py` and every code must round-trip.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from graphrec_sdk import (
    AuthenticationError,
    ConflictError,
    GraphRecError,
    InternalError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExhaustedError,
    RateLimitedError,
    UnavailableError,
    ValidationError,
)
from graphrec_sdk.errors import error_from
from tests.sdk.conftest import Recorder, Reply, envelope, make_client
from tests.sdk.fixtures import RECOMMENDATION

ROOT = Path(__file__).resolve().parents[2]
SERVER_ERRORS = (ROOT / "graphrec" / "common" / "errors.py").read_text()
SERVER_COPY = (ROOT / "graphrec" / "common" / "error_copy.py").read_text()

CLASSES = re.findall(
    r'^\s{4}[A-Z_]+ = "(\w+)"$',
    SERVER_ERRORS[SERVER_ERRORS.index("class ErrorClass") :].split("\n\n\n")[0],
    re.MULTILINE,
)
CODES = re.findall(
    r'^\s{4}"(\w+)":',
    SERVER_COPY[SERVER_COPY.index("ERROR_COPY: dict[str, str] = {") :],
    re.MULTILINE,
)

DEFAULT_STATUS = {
    "validation": 422,
    "conflict": 409,
    "limit": 429,
    "unavailable": 503,
    "auth": 401,
    "not_found": 404,
    "internal": 500,
}


def test_the_class_list_was_actually_read() -> None:
    # A regex that silently matches nothing would make every test below vacuous.
    assert len(CLASSES) == 7, CLASSES
    assert len(CODES) >= 80, len(CODES)


@pytest.mark.parametrize("error_class", CLASSES)
def test_every_class_the_server_defines_maps_to_a_subclass(error_class: str) -> None:
    status = DEFAULT_STATUS[error_class]
    error = error_from(status, envelope(error_class, "some_code"), "req-1")
    assert isinstance(error, GraphRecError)
    assert type(error) is not GraphRecError, f"{error_class} falls through to the base class"
    assert error.error_class == error_class
    assert error.status == status


@pytest.mark.parametrize("code", CODES)
def test_every_code_in_the_server_copy_round_trips(code: str) -> None:
    error = error_from(422, envelope("validation", code), "req-1")
    assert error.code == code
    assert code in str(error)


def test_403_is_class_auth_and_still_gets_its_own_type() -> None:
    # The envelope calls it `auth`, the same word a 401 uses. Only the status
    # separates "we do not know who you are" from "we know, and no" — so the
    # status is what the mapping looks at first.
    error = error_from(403, envelope("auth", "insufficient_scope"), "req-1")
    assert isinstance(error, PermissionDeniedError)
    assert isinstance(error, AuthenticationError), "one `except` should still catch both"
    error_401 = error_from(401, envelope("auth", "invalid_credentials"), "req-1")
    assert isinstance(error_401, AuthenticationError)
    assert not isinstance(error_401, PermissionDeniedError)


def test_the_two_kinds_of_429_are_different_types() -> None:
    limited = error_from(
        429, envelope("limit", "rate_limited", retry_after_seconds=2, retryable=True), "req-1"
    )
    exhausted = error_from(429, envelope("limit", "recommendation_quota_exhausted"), "req-1")

    assert isinstance(limited, RateLimitedError)
    assert isinstance(exhausted, QuotaExhaustedError)
    # Same status, same class, opposite remedies: one clears in seconds, the
    # other not until the billing period turns over.
    assert limited.is_transient
    assert not exhausted.is_transient
    assert exhausted.retry_after_seconds is None


@pytest.mark.parametrize(
    ("error_class", "code", "expected"),
    [
        ("validation", "invalid_request", ValidationError),
        ("conflict", "product_sync_in_progress", ConflictError),
        ("unavailable", "service_unavailable", UnavailableError),
        ("not_found", "submission_not_found", NotFoundError),
        ("internal", "internal_error", InternalError),
    ],
)
def test_a_class_becomes_the_type_a_caller_would_guess(
    error_class: str, code: str, expected: type[GraphRecError]
) -> None:
    error = error_from(DEFAULT_STATUS[error_class], envelope(error_class, code), None)
    assert isinstance(error, expected)


def test_field_errors_survive_the_crossing() -> None:
    payload = envelope(
        "validation",
        "invalid_request",
        field_errors=[{"field": "events.0.occurred_at", "reason": "must include a timezone"}],
    )
    error = error_from(422, payload, "req-1")
    assert isinstance(error, ValidationError)
    assert [(f.field, f.reason) for f in error.field_errors] == [
        ("events.0.occurred_at", "must include a timezone")
    ]
    # The one thing a caller actually wants to print.
    assert "events.0.occurred_at" in str(error)


def test_a_response_that_is_not_an_envelope_still_becomes_a_typed_error() -> None:
    # Caddy's 413 arrives before the application sees the request, and a proxy's
    # 502 is HTML. Neither is a reason for the caller to hold a `JSONDecodeError`.
    too_large = error_from(413, "<html>413 Request Entity Too Large</html>", "req-1")
    assert isinstance(too_large, ValidationError)
    assert too_large.code == "request_too_large"

    gateway = error_from(502, None, None)
    assert isinstance(gateway, UnavailableError)
    assert gateway.is_transient


def test_an_unknown_status_is_not_a_crash() -> None:
    error = error_from(418, {"detail": "teapot"}, "req-1")
    assert isinstance(error, GraphRecError)
    assert error.status == 418


def test_the_reference_is_the_request_id_the_server_echoed() -> None:
    recorder = Recorder(
        replies=[Reply(status=409, body=envelope("conflict", "product_sync_in_progress"))]
    )
    with make_client(recorder) as client, pytest.raises(ConflictError) as caught:
        client.catalog.sync(sync_id="s-1", products=[{"external_id": "sku-1", "title": "T"}])

    assert caught.value.reference == "ref-0001"
    # `reference` is what the console's support search takes; `request_id` is
    # what the transport saw on the wire. They are usually the same value and
    # occasionally are not, so both are kept.
    assert caught.value.request_id == "srv-req-1"


def test_a_success_is_not_an_error() -> None:
    recorder = Recorder(replies=[Reply(body=RECOMMENDATION)])
    with make_client(recorder) as client:
        answer = client.recommendations.for_customer(request_id="r-1", customer_id="c-1")
    assert answer.request_id == RECOMMENDATION["request_id"]
