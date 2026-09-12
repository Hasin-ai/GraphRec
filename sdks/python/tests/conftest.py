"""Shared fixtures: an in-memory GraphRec API built on ``httpx.MockTransport``."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

import httpx
import pytest

from graphrec_sdk import AsyncGraphRec, GraphRec, RetryPolicy

API_KEY = "gr_live_" + "A" * 43
BASE_URL = "https://graphrec.test"

Handler = Callable[[httpx.Request], Union[httpx.Response, Dict[str, Any], List[Any]]]


@dataclass
class Recorded:
    request: httpx.Request

    @property
    def method(self) -> str:
        return self.request.method

    @property
    def path(self) -> str:
        return self.request.url.raw_path.decode().split("?", 1)[0]

    @property
    def headers(self) -> httpx.Headers:
        return self.request.headers

    def json(self) -> Any:
        return json.loads(self.request.content) if self.request.content else None


@dataclass
class MockAPI:
    """Route table of ``(METHOD, path regex) -> handler`` plus a request log."""

    routes: List[Tuple[str, re.Pattern[str], Handler]] = field(default_factory=list)
    calls: List[Recorded] = field(default_factory=list)

    def on(
        self, method: str, path: str, handler: Union[Handler, Dict[str, Any], List[Any]]
    ) -> None:
        pattern = re.compile("^" + path + "$")
        fn: Handler = handler if callable(handler) else (lambda _req, _v=handler: _v)
        self.routes.insert(0, (method.upper(), pattern, fn))

    def queue(
        self, method: str, path: str, *responses: Union[httpx.Response, Dict[str, Any]]
    ) -> None:
        """Serve ``responses`` in order (the last one repeats)."""

        pending = list(responses)

        def handler(_req: httpx.Request) -> Union[httpx.Response, Dict[str, Any]]:
            return pending.pop(0) if len(pending) > 1 else pending[0]

        self.on(method, path, handler)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.calls.append(Recorded(request))
        path = request.url.raw_path.decode().split("?", 1)[0]
        for method, pattern, handler in self.routes:
            if method == request.method and pattern.match(path):
                result = handler(request)
                if isinstance(result, httpx.Response):
                    return result
                return httpx.Response(200, json=result)
        return error(404, "resource_not_found", f"No mock for {request.method} {path}")

    def last(self) -> Recorded:
        return self.calls[-1]

    def paths(self) -> List[str]:
        return [f"{c.method} {c.path}" for c in self.calls]


def error(
    status: int,
    code: str,
    message: str = "error",
    *,
    retryable: bool = False,
    retry_after: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    correlation_id: str = "11111111-2222-4333-8444-555555555555",
) -> httpx.Response:
    body: Dict[str, Any] = {
        "code": code,
        "message": message,
        "correlation_id": correlation_id,
        "retryable": retryable,
    }
    headers = {"X-Correlation-ID": correlation_id}
    if retry_after is not None:
        body["retry_after_seconds"] = retry_after
        headers["Retry-After"] = str(retry_after)
    if details:
        body["details"] = details
    return httpx.Response(status, json={"error": body}, headers=headers)


@pytest.fixture
def api() -> MockAPI:
    return MockAPI()


@pytest.fixture
def sleeps() -> List[float]:
    return []


def make_client(api: MockAPI, sleeps: Optional[List[float]] = None, **kwargs: Any) -> GraphRec:
    kwargs.setdefault("api_key", API_KEY)
    kwargs.setdefault("retry_policy", RetryPolicy(max_retries=2, jitter=0.0))
    client = GraphRec(
        base_url=BASE_URL,
        http_client=httpx.Client(transport=httpx.MockTransport(api)),
        use_env=False,
        **kwargs,
    )
    if sleeps is not None:
        client._api._sleep = sleeps.append
    return client


def make_async_client(
    api: MockAPI, sleeps: Optional[List[float]] = None, **kwargs: Any
) -> AsyncGraphRec:
    kwargs.setdefault("api_key", API_KEY)
    kwargs.setdefault("retry_policy", RetryPolicy(max_retries=2, jitter=0.0))
    client = AsyncGraphRec(
        base_url=BASE_URL,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(api)),
        use_env=False,
        **kwargs,
    )
    if sleeps is not None:

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        client._api._sleep = fake_sleep
    return client


@pytest.fixture
def client(api: MockAPI, sleeps: List[float]) -> Iterator[GraphRec]:
    with make_client(api, sleeps) as graphrec:
        yield graphrec


# -- canned server payloads ---------------------------------------------------------

UUID_A = "3f0e2b8e-9c1d-4c1e-8e2a-000000000001"
UUID_B = "3f0e2b8e-9c1d-4c1e-8e2a-000000000002"
NOW = "2026-09-11T10:00:00Z"


def product(external_id: str = "sku-1", **overrides: Any) -> Dict[str, Any]:
    data = {
        "id": UUID_A,
        "external_id": external_id,
        "title": "Linen shirt",
        "description": None,
        "price": "49.90",
        "category": "apparel",
        "is_active": True,
        "availability_status": "available",
        "metadata": {"brand": "Acme"},
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return data


def bulk_result(created: int = 1, updated: int = 0) -> Dict[str, Any]:
    return {
        "accepted_count": created + updated,
        "created_count": created,
        "updated_count": updated,
        "skipped_count": 0,
        "rejected_count": 0,
        "failures": [],
    }


def event_batch(accepted: int = 1, duplicates: int = 0, batch_id: str = UUID_A) -> Dict[str, Any]:
    return {
        "id": batch_id,
        "status": "completed",
        "accepted_count": accepted,
        "duplicate_count": duplicates,
        "rejected_count": 0,
        "created_at": NOW,
    }


def tokens(access: str = "access-1", expires_in: int = 900) -> Dict[str, Any]:
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": "refresh",
        "user_role": "tenant_administrator",
        "scopes": ["keys:write", "billing:read"],
    }


def api_key(secret: bool = False, **overrides: Any) -> Dict[str, Any]:
    data = {
        "id": UUID_A,
        "name": "storefront",
        "prefix": "gr_live_AbCdEfGh",
        "scopes": ["catalog:read"],
        "status": "active",
        "expires_at": None,
        "created_at": NOW,
        "last_used_at": None,
        "revoked_at": None,
        "grace_expires_at": None,
    }
    if secret:
        data["secret"] = "gr_live_" + "S" * 43
    data.update(overrides)
    return data


def recommendations(ids: Tuple[str, ...] = ("sku-1", "sku-2", "sku-3")) -> Dict[str, Any]:
    return {
        "request_id": "rec-abc123",
        "items": [{"external_product_id": pid, "position": i + 1} for i, pid in enumerate(ids)],
        "model_version_id": UUID_B,
        "strategy": "personalized",
        "fallback_used": False,
        "fallback_tier": "none",
    }


def feedback(feedback_type: str, event_id: str = "fbk_1") -> Dict[str, Any]:
    return {
        "event_id": event_id,
        "feedback_type": feedback_type,
        "accepted": True,
        "duplicate": False,
        "received_at": NOW,
    }


def model_version(status: str = "eligible", version_id: str = UUID_B) -> Dict[str, Any]:
    return {
        "id": version_id,
        "version_tag": "v20260911-simpli",
        "model_type": "simplified_dgsr",
        "status": status,
        "metrics": {"recall_at_10": 0.85},
        "artifact_uri": "rustfs://graphrec-models/x.safetensors",
        "qdrant_collection": None,
        "created_at": NOW,
        "activated_at": NOW if status == "active" else None,
    }


def training_job(status: str = "succeeded", job_id: str = UUID_A) -> Dict[str, Any]:
    return {
        "id": job_id,
        "model_type": "simplified_dgsr",
        "status": status,
        "configuration": {"epochs": 10},
        "dataset_snapshot_id": None,
        "model_version_id": UUID_B,
        "qdrant_collection": None,
        "failure_reason": None,
        "created_at": NOW,
        "completed_at": NOW,
    }


def snapshot() -> Dict[str, Any]:
    return {
        "id": UUID_A,
        "tenant_id": UUID_B,
        "training_job_id": None,
        "cutoff_at": NOW,
        "event_count": 10,
        "product_count": 3,
        "user_count": 2,
        "artifact_uri": "rustfs://graphrec-datasets/x.jsonl",
        "checksum": "0" * 64,
        "created_at": NOW,
    }
