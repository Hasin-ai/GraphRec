from __future__ import annotations

import json
from typing import List

import httpx
import pytest

import graphrec_sdk as g
from graphrec_sdk import errors

from .conftest import API_KEY, BASE_URL, MockAPI, error, make_client, product, tokens


def test_standard_headers_and_api_key_scheme(client: g.GraphRec, api: MockAPI) -> None:
    api.on("GET", "/v1/products/sku-1", product())
    client.products.get("sku-1")
    sent = api.last()
    assert sent.headers["Accept"] == "application/json"
    assert sent.headers["Authorization"] == f"ApiKey {API_KEY}"
    assert sent.headers["User-Agent"].startswith("graphrec-sdk-python/")
    assert len(sent.headers["X-Correlation-ID"]) == 36
    assert "Content-Type" not in sent.headers


def test_json_post_is_compact_and_typed(client: g.GraphRec, api: MockAPI) -> None:
    api.on("PUT", "/v1/products/sku-1", product())
    client.products.upsert({"external_id": "sku-1", "title": "Linen shirt", "price": 49.9})
    sent = api.last()
    assert sent.headers["Content-Type"] == "application/json"
    assert b": " not in sent.request.content
    body = sent.json()
    assert body["price"] == "49.9"
    assert body["external_id"] == "sku-1"


def test_bodyless_action_post_still_declares_json(client: g.GraphRec, api: MockAPI) -> None:
    api.on("POST", "/v1/products/sku%201:disable", product("sku 1", is_active=False))
    result = client.products.disable("sku 1")
    sent = api.last()
    assert result.is_active is False
    assert sent.headers["Content-Type"] == "application/json"
    assert sent.headers["Content-Length"] == "0"
    assert sent.request.content == b""


def test_path_parameters_are_percent_encoded(client: g.GraphRec, api: MockAPI) -> None:
    api.on("GET", "/v1/products/a%2Fb%3Fc", product("a/b?c"))
    assert client.products.get("a/b?c").external_id == "a/b?c"


def test_public_routes_never_receive_credentials(client: g.GraphRec, api: MockAPI) -> None:
    api.on("POST", "/v1/auth/login", tokens())
    client.auth.login(email="dev@shop.test", password="secret-password")
    assert "Authorization" not in api.last().headers


@pytest.mark.parametrize(
    ("status", "code", "exc_type"),
    [
        (400, "malformed_request", errors.MalformedRequestError),
        (401, "authentication_failed", errors.AuthenticationError),
        (401, "token_expired", errors.TokenExpiredError),
        (403, "insufficient_scope", errors.PermissionDeniedError),
        (404, "resource_not_found", errors.NotFoundError),
        (409, "duplicate_resource", errors.DuplicateResourceError),
        (409, "idempotency_conflict", errors.IdempotencyConflictError),
        (409, "state_conflict", errors.StateConflictError),
        (409, "conflict", errors.StateConflictError),
        (413, "payload_too_large", errors.PayloadTooLargeError),
        (422, "validation_failed", errors.RequestValidationError),
        (429, "quota_exceeded", errors.QuotaExceededError),
        (500, "boom", errors.InternalServerError),
        (418, "teapot", errors.APIStatusError),
    ],
)
def test_error_envelope_maps_to_exception(
    api: MockAPI, sleeps: List[float], status: int, code: str, exc_type: type
) -> None:
    api.on("GET", "/v1/products/sku-1", lambda _r: error(status, code, "nope"))
    with make_client(api, sleeps) as client, pytest.raises(exc_type) as info:
        client.products.get("sku-1")
    exc = info.value
    assert type(exc) is exc_type
    assert exc.status_code == status
    assert exc.code == code
    assert exc.correlation_id == "11111111-2222-4333-8444-555555555555"
    assert code in str(exc)
    assert sleeps == []


def test_validation_error_exposes_field_errors(client: g.GraphRec, api: MockAPI) -> None:
    details = {"fields": [{"field": "products.0.title", "message": "Field required"}]}
    api.on(
        "POST",
        "/v1/products:bulk-upsert",
        lambda _r: error(422, "validation_failed", details=details),
    )
    with pytest.raises(errors.RequestValidationError) as info:
        client.products.bulk_upsert([{"external_id": "sku-1", "title": "x"}])
    assert info.value.field_errors == [errors.FieldError("products.0.title", "Field required")]


def test_non_json_error_body_is_handled(client: g.GraphRec, api: MockAPI) -> None:
    api.on("GET", "/v1/products", lambda _r: httpx.Response(502, text="<html>Bad gateway</html>"))
    with pytest.raises(errors.InternalServerError) as info:
        client.products.list()
    assert info.value.code == "http_502"


def test_rate_limit_is_retried_with_retry_after(
    client: g.GraphRec, api: MockAPI, sleeps: List[float]
) -> None:
    api.queue(
        "POST",
        "/v1/model-versions",
        error(429, "rate_limit_exceeded", retryable=True, retry_after=7),
        {
            "id": "3f0e2b8e-9c1d-4c1e-8e2a-000000000002",
            "version_tag": "v1",
            "model_type": "simplified_dgsr",
            "status": "eligible",
            "metrics": {},
            "created_at": "2026-09-11T10:00:00Z",
        },
    )
    version = client.model_versions.create(version_tag="v1")
    assert version.version_tag == "v1"
    assert sleeps == [7.0]
    first, second = api.calls
    assert first.headers["X-Correlation-ID"] == second.headers["X-Correlation-ID"]


def test_retryable_503_uses_backoff_then_gives_up(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", "/v1/usage", lambda _r: error(503, "service_unavailable", retryable=True))
    with make_client(api, sleeps) as client, pytest.raises(errors.ServiceUnavailableError):
        client.usage.get()
    assert len(api.calls) == 3
    assert sleeps == [0.5, 1.0]


def test_quota_exceeded_is_never_retried(
    client: g.GraphRec, api: MockAPI, sleeps: List[float]
) -> None:
    api.on("POST", "/v1/training-jobs", lambda _r: error(429, "quota_exceeded", retryable=True))
    with pytest.raises(errors.QuotaExceededError) as info:
        client.training_jobs.create()
    assert info.value.retryable is False
    assert len(api.calls) == 1 and sleeps == []


def test_retry_after_above_ceiling_is_raised(api: MockAPI, sleeps: List[float]) -> None:
    api.on("GET", "/v1/usage", lambda _r: error(429, "rate_limit_exceeded", retry_after=3600))
    with make_client(api, sleeps) as client, pytest.raises(errors.RateLimitError) as info:
        client.usage.get()
    assert info.value.retry_after_seconds == 3600
    assert len(api.calls) == 1


def test_read_timeout_retried_only_for_idempotent_routes(api: MockAPI, sleeps: List[float]) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    api.on("GET", "/v1/products", timeout)
    api.on("POST", "/v1/training-jobs", timeout)
    with make_client(api, sleeps) as client:
        with pytest.raises(errors.APITimeoutError):
            client.products.list()
        assert len(api.calls) == 3
        with pytest.raises(errors.APITimeoutError):
            client.training_jobs.create()
        assert len(api.calls) == 4


def test_connect_error_is_retried_even_for_non_idempotent_routes(
    api: MockAPI, sleeps: List[float]
) -> None:
    attempts = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"status": "ok"})

    api.on("GET", "/healthz", flaky)
    with make_client(api, sleeps) as client:
        assert client.health() == {"status": "ok"}
    assert sleeps == [0.5]


def test_unexpected_success_body_raises_response_validation_error(
    client: g.GraphRec, api: MockAPI
) -> None:
    api.on("GET", "/v1/products/sku-1", {"unexpected": True})
    with pytest.raises(errors.APIResponseValidationError) as info:
        client.products.get("sku-1")
    assert info.value.body == {"unexpected": True}


def test_unknown_response_fields_are_preserved(client: g.GraphRec, api: MockAPI) -> None:
    api.on("GET", "/v1/products/sku-1", product(new_server_field="hello"))
    result = client.products.get("sku-1")
    assert result.model_extra == {"new_server_field": "hello"}


def test_credential_configuration_errors(api: MockAPI) -> None:
    with make_client(api, api_key=None) as anonymous, pytest.raises(errors.ConfigurationError):
        anonymous.products.list()
    with make_client(api) as keyed, pytest.raises(errors.ConfigurationError, match="bearer"):
        keyed.api_keys.list()
    with (
        make_client(api) as keyed,
        pytest.raises(errors.ConfigurationError, match="PLATFORM_ADMIN_TOKEN"),
    ):
        keyed.platform.list_tenants()
    assert api.calls == []
    with pytest.raises(errors.ConfigurationError):
        g.GraphRec(api_key=API_KEY, access_token="t", use_env=False)
    with pytest.raises(errors.ConfigurationError):
        g.GraphRec(email="a@b.test", use_env=False)
    with pytest.raises(errors.ConfigurationError):
        g.GraphRec(base_url="graphrec.test", use_env=False)


def test_environment_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHREC_BASE_URL", "https://env.graphrec.test/")
    monkeypatch.setenv("GRAPHREC_API_KEY", API_KEY)
    with g.GraphRec() as client:
        assert client.base_url == "https://env.graphrec.test"
        assert isinstance(client.credentials, g.ApiKeyAuth)
        assert API_KEY not in repr(client)
    with g.GraphRec(use_env=False) as client:
        assert client.credentials is None


def test_with_credentials_shares_the_connection_pool(client: g.GraphRec, api: MockAPI) -> None:
    api.on(
        "GET",
        "/v1/subscription",
        {
            "plan_code": "free",
            "status": "active",
            "period_start": "2026-09-01T00:00:00Z",
            "period_end": "2026-10-01T00:00:00Z",
            "limits": {"accepted_events": 50000},
            "project_defaults": True,
        },
    )
    admin = client.with_credentials(access_token="jwt-token")
    assert admin._api._http is client._api._http
    admin.subscription.get()
    assert api.last().headers["Authorization"] == "Bearer jwt-token"
    admin.close()
    assert not client._api._http.is_closed


def test_default_headers_and_idempotency_key(api: MockAPI) -> None:
    api.on(
        "POST",
        "/v1/tenants",
        {
            "id": "3f0e2b8e-9c1d-4c1e-8e2a-000000000001",
            "name": "Shop",
            "status": "active",
            "created_at": "2026-09-11T10:00:00Z",
            "administrator_email": "owner@shop.test",
            "next_step": "setup",
        },
    )
    with make_client(api, api_key=None, default_headers={"X-Shop": "eu-1"}) as client:
        client.tenants.register(name="Shop", admin_email="owner@shop.test", idempotency_key="reg-1")
    sent = api.last()
    assert sent.headers["Idempotency-Key"] == "reg-1"
    assert sent.headers["X-Shop"] == "eu-1"
    assert json.loads(sent.request.content) == {"name": "Shop", "admin_email": "owner@shop.test"}


def test_base_url_path_prefix_is_kept(api: MockAPI) -> None:
    client = g.GraphRec(
        base_url=BASE_URL + "/graphrec/",
        api_key=API_KEY,
        http_client=httpx.Client(transport=httpx.MockTransport(api)),
        use_env=False,
    )
    api.on("GET", "/graphrec/v1/products", {"items": [], "total": 0})
    assert len(client.products.list()) == 0
