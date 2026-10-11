"""Error envelope: ``{"error": {"code", "message", "correlationId"?}}``.

Upstream GraphRec failures are translated, never forwarded: no authorization
headers, no stack traces, no upstream bodies.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from graphrec_sdk import (
    APIConnectionError,
    APIError,
    APIStatusError,
    InputValidationError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
)


class StoreError(Exception):
    def __init__(self, status: int, code: str, message: str, correlation_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.correlation_id = correlation_id


def error_response(status: int, code: str, message: str, correlation_id: Optional[str] = None) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if correlation_id:
        body["error"]["correlationId"] = correlation_id
    return JSONResponse(status_code=status, content=body)


def translate_api_error(error: APIError) -> StoreError:
    cid = error.correlation_id
    if isinstance(error, NotFoundError):
        return StoreError(404, "not_found", "That product does not exist in this store.", cid)
    if isinstance(error, PermissionDeniedError):
        return StoreError(502, "upstream_scope", "The storefront's GraphRec key lacks a required scope.", cid)
    if isinstance(error, QuotaExceededError):
        return StoreError(503, "upstream_quota", "The demo tenant's GraphRec quota is exhausted.", cid)
    if isinstance(error, RateLimitError):
        return StoreError(503, "upstream_rate_limited", "GraphRec is rate limiting the storefront. Try again shortly.", cid)
    if isinstance(error, APIConnectionError):
        return StoreError(503, "upstream_unreachable", "GraphRec could not be reached.", cid)
    if isinstance(error, APIStatusError):
        return StoreError(502, "upstream_error", f"GraphRec answered {error.status_code} {error.code}.", cid)
    return StoreError(502, "upstream_error", "GraphRec request failed.", cid)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StoreError)
    async def _store(_: Request, exc: StoreError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.correlation_id)

    @app.exception_handler(APIError)
    async def _api(_: Request, exc: APIError) -> JSONResponse:
        t = translate_api_error(exc)
        return error_response(t.status, t.code, t.message, t.correlation_id)

    @app.exception_handler(InputValidationError)
    async def _sdk_input(_: Request, exc: InputValidationError) -> JSONResponse:
        return error_response(422, "validation_failed", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return error_response(422, "validation_failed", f"{loc}: {first.get('msg', 'invalid')}" if loc else "Invalid request body.")

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover - safety net
        return error_response(500, "internal_error", "The storefront hit an unexpected error.")
