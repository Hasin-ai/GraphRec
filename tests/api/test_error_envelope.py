"""The error envelope — every failure, without exception.

`class`, `reason` and `reference` are published to tenants by the console's
/integration page. These tests hold that contract, including the rule that a 404
never names the resource type.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from pydantic import BaseModel

from graphrec.common.errors import (
    ConflictError,
    ErrorClass,
    LimitError,
    NotFoundError,
    UnavailableError,
    ValidationError,
)


@pytest.fixture
def error_app(settings):
    """An app with routes that raise each error class deliberately."""
    from apps.control_api.main import create_app

    app = create_app(settings)
    router = APIRouter(prefix="/v1/_test")

    @router.get("/conflict")
    async def _conflict() -> None:
        raise ConflictError("product_already_exists", copy_args={"external_product_id": "SKU-4471"})

    @router.get("/validation")
    async def _validation() -> None:
        raise ValidationError("reason_required").with_field("reason", "A reason is required.")

    @router.get("/limit")
    async def _limit() -> None:
        raise LimitError(
            "product_quota_exhausted",
            copy_args={"used": "50,000", "limit": "50,000", "plan_code": "GROWTH"},
            retry_after_seconds=60,
        )

    @router.get("/unavailable")
    async def _unavailable() -> None:
        raise UnavailableError()

    @router.get("/not-found")
    async def _not_found() -> None:
        raise NotFoundError()

    @router.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("connection to 10.0.0.7 failed for tenant 3f81 with key gr_live_ABC123")

    app.include_router(router)
    return app


@pytest.fixture
def error_client(error_app):
    from fastapi.testclient import TestClient

    with TestClient(error_app, raise_server_exceptions=False) as client:
        yield client


def test_envelope_carries_the_three_published_fields(error_client) -> None:
    body = error_client.get("/v1/_test/conflict").json()
    assert set(body) == {"error"}
    for field in ("class", "reason", "reference"):
        assert field in body["error"], f"{field} is published on /integration and must be present"


def test_class_is_serialised_as_class_not_error_class(error_client) -> None:
    """The wire name is `class`, a Python keyword. It must not leak as `error_class`."""
    body = error_client.get("/v1/_test/conflict").json()["error"]
    assert body["class"] == "conflict"
    assert "error_class" not in body


@pytest.mark.parametrize(
    ("path", "status", "error_class"),
    [
        ("/v1/_test/validation", 422, ErrorClass.VALIDATION),
        ("/v1/_test/conflict", 409, ErrorClass.CONFLICT),
        ("/v1/_test/limit", 429, ErrorClass.LIMIT),
        ("/v1/_test/unavailable", 503, ErrorClass.UNAVAILABLE),
        ("/v1/_test/not-found", 404, ErrorClass.NOT_FOUND),
        ("/v1/_test/boom", 500, ErrorClass.INTERNAL),
    ],
)
def test_each_class_maps_to_its_status(error_client, path, status, error_class) -> None:
    response = error_client.get(path)
    assert response.status_code == status
    assert response.json()["error"]["class"] == error_class.value


def test_reason_is_the_approved_copy(error_client) -> None:
    """The console's sentence, not `API.md`'s shorter paraphrase of it.

    This assertion previously held the paraphrase. `API.md` is not binding
    (BUILD_PROMPT §0) and the prototype is; the second sentence is the half that
    tells the tenant what to do next, and dropping it is exactly the drift the
    copy catalogue exists to prevent. See dc.html L1604.
    """
    body = error_client.get("/v1/_test/conflict").json()["error"]
    assert body["reason"] == (
        "A product with identifier SKU-4471 already exists. "
        "Use a different identifier or update the existing product."
    )


def test_limit_error_names_the_numbers(error_client) -> None:
    """§9 — a 429 must carry the numbers; the console renders them."""
    body = error_client.get("/v1/_test/limit").json()["error"]
    assert "50,000 of 50,000" in body["reason"]
    assert "GROWTH" in body["reason"]


def test_limit_error_sets_retry_after(error_client) -> None:
    response = error_client.get("/v1/_test/limit")
    assert response.headers["Retry-After"] == "60"
    assert response.json()["error"]["retry_after_seconds"] == 60


def test_field_errors_are_additive(error_client) -> None:
    body = error_client.get("/v1/_test/validation").json()["error"]
    assert body["field_errors"] == [{"field": "reason", "reason": "A reason is required."}]


def test_reference_matches_the_response_request_id(error_client) -> None:
    """A tenant quoting a reference must lead to that request's log lines."""
    response = error_client.get("/v1/_test/conflict")
    assert response.json()["error"]["reference"] == response.headers["X-Request-Id"]


def test_not_found_never_names_the_resource_type(error_client) -> None:
    """Gate 4 — a foreign resource is indistinguishable from a missing one."""
    body = error_client.get("/v1/_test/not-found").json()["error"]
    reason = body["reason"].lower()
    for noun in ("product", "model", "version", "job", "credential", "user", "submission"):
        assert noun not in reason


def test_unhandled_exception_never_leaks_its_message(error_client) -> None:
    """NR-NF-06 — no host, tenant identifier or credential in an error body."""
    response = error_client.get("/v1/_test/boom")
    serialised = response.text
    assert response.status_code == 500
    for secret in ("10.0.0.7", "3f81", "gr_live_ABC123", "RuntimeError", "Traceback"):
        assert secret not in serialised


def test_unhandled_exception_still_carries_a_quotable_reference(error_client) -> None:
    body = error_client.get("/v1/_test/boom").json()["error"]
    assert body["reference"]
    assert body["class"] == "internal"


def test_unknown_route_returns_the_envelope_not_fastapis_detail(error_client) -> None:
    """FastAPI's default is `{"detail": ...}`. A client must see one shape only."""
    body = error_client.get("/v1/does-not-exist").json()
    assert "detail" not in body
    assert body["error"]["class"] == "not_found"


class _ProductBody(BaseModel):
    """Declared at module scope deliberately.

    This module carries `from __future__ import annotations`, so every annotation
    reaches FastAPI as a string and is resolved against the *module* globals. A
    model defined inside a test function is invisible there, and FastAPI quietly
    demotes the parameter to a query scalar instead of a body model — which looks
    like a handler bug and is not one.
    """

    external_product_id: str
    title: str


def test_pydantic_rejection_renders_as_a_validation_envelope(settings) -> None:
    """A 422 from the framework is shaped like a 422 from domain code."""
    from fastapi.testclient import TestClient

    from apps.control_api.main import create_app

    app = create_app(settings)
    router = APIRouter(prefix="/v1/_test")

    @router.post("/products")
    async def _create(body: _ProductBody) -> dict[str, str]:
        return {"external_product_id": body.external_product_id}

    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/v1/_test/products", json={"title": "Brass hinge"})

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["class"] == "validation"
    assert body["code"] == "invalid_request"
    assert [fe["field"] for fe in body["field_errors"]] == ["external_product_id"]


def test_framework_422_never_echoes_the_rejected_input(settings) -> None:
    """Pydantic puts the offending value in `input`. It must not be relayed.

    NR-NF-06 — a rejected body can hold a password or a raw event payload.
    """
    from fastapi.testclient import TestClient

    from apps.control_api.main import create_app

    app = create_app(settings)
    router = APIRouter(prefix="/v1/_test")

    @router.post("/products")
    async def _create(body: _ProductBody) -> dict[str, str]:
        return {"external_product_id": body.external_product_id}

    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/_test/products",
            json={"title": "Brass hinge", "password": "hunter2-should-never-be-echoed"},
        )

    assert response.status_code == 422
    assert "hunter2-should-never-be-echoed" not in response.text
    assert "input" not in response.text
