from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from graphrec_core.errors import ApiError
from graphrec_core.auth.audit import record_public_login_denial
from graphrec_core.registration.audit import record_public_registration_denial


def correlation_id_for(request: Request) -> UUID:
    value = getattr(request.state, "correlation_id", None)
    return value if isinstance(value, UUID) else uuid4()


def error_response(
    *,
    correlation_id: UUID,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    retry_after_seconds: int | None = None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "correlation_id": str(correlation_id),
        "retryable": retryable,
    }
    if retry_after_seconds is not None:
        error["retry_after_seconds"] = retry_after_seconds
    if details:
        error["details"] = details
    headers = {"X-Correlation-ID": str(correlation_id)}
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(retry_after_seconds)
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(
        correlation_id=correlation_id_for(request),
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        retry_after_seconds=exc.retry_after_seconds,
        details=exc.details,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    malformed_json = any(error.get("type") == "json_invalid" for error in exc.errors())
    if request.url.path == "/v1/tenants":
        record_public_registration_denial(
            event_type="registration_validation_denied",
            correlation_id=correlation_id_for(request),
            source=request.client.host if request.client else "unknown",
            detail={
                "reason": "malformed_json" if malformed_json else "validation_failed",
                "fields": [
                    ".".join(str(part) for part in error.get("loc", ()) if part != "body")
                    for error in exc.errors()
                ],
            },
        )
    elif request.url.path == "/v1/auth/login":
        record_public_login_denial(
            event_type="login_validation_denied",
            correlation_id=correlation_id_for(request),
            source=request.client.host if request.client else "unknown",
            detail={
                "reason": "malformed_json" if malformed_json else "validation_failed",
                "fields": [
                    ".".join(str(part) for part in error.get("loc", ()) if part != "body")
                    for error in exc.errors()
                ],
            },
        )
    if malformed_json:
        return error_response(
            correlation_id=correlation_id_for(request),
            status_code=400,
            code="malformed_request",
            message="The JSON request body is malformed",
        )
    safe_fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
            "message": error.get("msg", "Invalid value"),
        }
        for error in exc.errors()
    ]
    return error_response(
        correlation_id=correlation_id_for(request),
        status_code=422,
        code="validation_failed",
        message="One or more request fields are invalid",
        details={"fields": safe_fields},
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(
            correlation_id=correlation_id_for(request),
            status_code=404,
            code="resource_not_found",
            message="The requested resource was not found",
        )
    return error_response(
        correlation_id=correlation_id_for(request),
        status_code=400,
        code="malformed_request",
        message="The request could not be processed",
    )
