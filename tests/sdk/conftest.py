"""Fixtures for the Python SDK's suite.

The SDK is exercised through `httpx.MockTransport` rather than through a mocked
method, for the same reason the TypeScript suite uses a recording fetch: these
tests assert on what was *sent* — the host, the path, the `Authorization`
header, the body of a retry — and a stub that only returns values cannot support
that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

TENANT = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
TENANT_HEX = "3f2b1c4d5e6f4a7b8c9d0e1f2a3b4c5d"
KEY = "gr_live_7Kq4.Zm9vYmFyYmF6cXV1eGNvcmdlZ3JhdWx0Z2FycGx5"
SECRET = "Zm9vYmFyYmF6cXV1eGNvcmdlZ3JhdWx0Z2FycGx5"
DOMAIN = "graphrec.example"

CONTROL = f"https://api.{DOMAIN}"
DATA = f"https://{TENANT_HEX}.serve.{DOMAIN}"


@dataclass
class Reply:
    status: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    #: Raised instead of answering — a connect or TLS failure.
    raises: Exception | None = None


@dataclass
class Recorder:
    """A tiny server. The last reply repeats, so "always 503" is one line."""

    replies: list[Reply]
    calls: list[httpx.Request] = field(default_factory=list)
    bodies: list[Any] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        import json

        reply = self.replies[min(len(self.calls), len(self.replies) - 1)]
        self.calls.append(request)
        self.bodies.append(json.loads(request.content) if request.content else None)
        if reply.raises is not None:
            raise reply.raises
        return httpx.Response(
            reply.status,
            json=reply.body if reply.body is not None else {},
            headers={"X-Request-Id": "srv-req-1", **reply.headers},
        )


def envelope(error_class: str, code: str, **extra: Any) -> dict[str, dict[str, Any]]:
    """The envelope, as `graphrec/common/errors.py` renders it."""
    return {
        "error": {
            "class": error_class,
            "code": code,
            "reason": f"copy for {code}",
            "reference": "ref-0001",
            "field_errors": [],
            "retryable": False,
            "retry_after_seconds": None,
            **extra,
        }
    }


@pytest.fixture
def recorder() -> Recorder:
    return Recorder(replies=[Reply()])


def make_client(recorder: Recorder, **options: Any):
    """A `GraphRec` wired to the recorder.

    `max_retries=0` by default: retries are exercised deliberately in
    `test_retry.py`, and a suite that slept for real would eventually be made
    fast by shortening the budget rather than by fixing the test.
    """
    from graphrec_sdk import GraphRec

    return GraphRec(
        api_key=KEY,
        tenant_id=TENANT,
        domain=DOMAIN,
        http_client=httpx.Client(transport=httpx.MockTransport(recorder.handle)),
        **{"max_retries": 0, **options},
    )


def make_async_client(recorder: Recorder, **options: Any):
    from graphrec_sdk import AsyncGraphRec

    return AsyncGraphRec(
        api_key=KEY,
        tenant_id=TENANT,
        domain=DOMAIN,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(recorder.handle)),
        **{"max_retries": 0, **options},
    )
