"""Exception handlers — every failure leaves as an envelope, without exception.

FastAPI's own validation errors and Starlette's HTTPException are translated
here too, so a 422 raised by Pydantic is indistinguishable in shape from one
raised by domain code. A client that has to handle two error shapes will handle
one of them badly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from graphrec.common.errors import (
    DEFAULT_STATUS,
    ErrorClass,
    ErrorEnvelope,
    FieldError,
    GraphRecError,
    InternalError,
    NotFoundError,
)
from graphrec.common.ids import new_request_reference
from graphrec.common.logging import get_logger, request_id_var

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = get_logger(__name__)

#: Starlette raises bare HTTPExceptions for a few transport-level conditions.
#: Map them onto our classes so they still render as an envelope.
_STATUS_TO_CLASS: dict[int, tuple[ErrorClass, str]] = {
    401: (ErrorClass.AUTH, "unauthenticated"),
    403: (ErrorClass.AUTH, "insufficient_role"),
    404: (ErrorClass.NOT_FOUND, "not_found"),
    405: (ErrorClass.VALIDATION, "invalid_request"),
    409: (ErrorClass.CONFLICT, "conflict"),
    413: (ErrorClass.VALIDATION, "request_too_large"),
    422: (ErrorClass.VALIDATION, "invalid_request"),
    429: (ErrorClass.LIMIT, "rate_limited"),
    503: (ErrorClass.UNAVAILABLE, "service_unavailable"),
}


def _reference() -> str:
    """The value the console shows and a tenant quotes back to support.

    Falls back to a fresh reference when no request id is bound, so an error
    raised from a worker still carries something quotable.
    """
    return request_id_var.get() or new_request_reference()


def render_error(request: Request, error: GraphRecError) -> JSONResponse:
    reference = _reference()
    body = error.to_body(reference)
    envelope = ErrorEnvelope(error=body)

    headers = {"X-Request-Id": reference}
    if error.retry_after_seconds is not None:
        headers["Retry-After"] = str(error.retry_after_seconds)

    return JSONResponse(
        status_code=error.status_code or DEFAULT_STATUS[error.error_class],
        content=envelope.model_dump(by_alias=True, mode="json"),
        headers=headers,
    )


async def graphrec_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GraphRecError)
    logger.warning(
        "request_failed",
        extra={
            "error_class": exc.error_class.value,
            "error_code": exc.code,
            "status": exc.status_code,
            "path": request.url.path,
        },
    )
    return render_error(request, exc)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Pydantic rejection -> a `validation` envelope with per-field reasons.

    An unknown request field lands here as a 422 rather than being silently
    dropped: silent acceptance hides client bugs (BUILD_PROMPT §5.1).
    """
    assert isinstance(exc, RequestValidationError)

    field_errors: list[FieldError] = []
    for raw in exc.errors():
        location = [str(part) for part in raw.get("loc", ()) if part not in ("body", "query")]
        field_errors.append(
            FieldError(
                field=".".join(location) or "body",
                # `msg` is Pydantic's own wording, which is safe: it describes the
                # shape of the input, never its content.
                reason=str(raw.get("msg", "This value cannot be accepted.")),
            )
        )

    error = GraphRecError(
        "invalid_request",
        error_class=ErrorClass.VALIDATION,
        field_errors=field_errors,
    )
    logger.info(
        "request_invalid",
        extra={"path": request.url.path, "field_count": len(field_errors)},
    )
    return render_error(request, error)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    error_class, code = _STATUS_TO_CLASS.get(
        exc.status_code, (ErrorClass.INTERNAL, "internal_error")
    )
    if exc.status_code == 404:
        # Never name the resource type — a foreign resource must be
        # indistinguishable from a missing one (gate 4).
        return render_error(request, NotFoundError())

    return render_error(
        request,
        GraphRecError(code, error_class=error_class, status_code=exc.status_code),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """The last resort.

    The exception's own message never reaches the client: it may carry a query
    fragment, a credential or another tenant's identifier (NR-NF-06). It is
    logged with the reference so the detail is recoverable internally.
    """
    logger.exception(
        "request_unhandled_error",
        extra={"path": request.url.path, "exception_type": type(exc).__name__},
    )
    return render_error(request, InternalError())


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(GraphRecError, graphrec_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
