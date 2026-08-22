"""Request middleware.

Two concerns, both of which must run before any handler:

* **Correlation.** Every response carries `X-Request-Id`, and a failure echoes
  the same value as `error.reference`, so a tenant reading a reference out of an
  error banner leads to that request's log lines.
* **Body limits (D7).** Per-endpoint, not global. The inherited single
  `MAX_REQUEST_BODY_BYTES=16384` is 37x too small for the 5,000-product sync the
  console offers, so bulk routes get their own ceiling.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders
from starlette.requests import Request

from graphrec.common.errors import ErrorClass, ValidationError
from graphrec.common.ids import new_request_id
from graphrec.common.logging import get_logger, request_id_var

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"

#: Routes that accept a bounded collection and therefore need the bulk ceiling.
#: Kept as a suffix list because the paths carry no tenant segment (NR-NF-02).
BULK_PATH_SUFFIXES: tuple[str, ...] = (
    "/products:bulk-upsert",
    "/events/batches",
)


def body_limit_for(path: str, default: int, bulk: int) -> int:
    return bulk if any(path.endswith(s) for s in BULK_PATH_SUFFIXES) else default


class RequestContextMiddleware:
    """Bind a request id for the life of the request and return it on the response.

    Written against the raw ASGI interface rather than BaseHTTPMiddleware: the
    latter runs the handler in a separate task, which loses the ContextVar
    binding that the logger depends on.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        supplied = headers.get(b"x-request-id", b"").decode("latin-1").strip()
        # A client-supplied value is echoed for tracing, but never trusted as a
        # log key beyond a sane length.
        request_id = supplied[:64] if supplied else new_request_id()

        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_holder.get("status"),
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)


class BodyLimitMiddleware:
    """Reject an oversize body as `413` with `error.class = "validation"`.

    Enforced by streaming rather than by trusting `Content-Length`, so a chunked
    request cannot bypass the ceiling. The console already renders a designed
    destination for this rejection ("Paste more than 5,000 products, or the word
    OVERSIZE", dc.html L1358).
    """

    def __init__(self, app: ASGIApp, *, default_limit: int, bulk_limit: int) -> None:
        self.app = app
        self.default_limit = default_limit
        self.bulk_limit = bulk_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        limit = body_limit_for(scope.get("path", ""), self.default_limit, self.bulk_limit)

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._reject(scope, receive, send, limit)
                    return
            except ValueError:
                pass  # a malformed header is the body parser's problem, not ours

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise ValidationError(
                        "request_too_large",
                        status_code=413,
                        copy_args={},
                    )
            return message

        await self.app(scope, limited_receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        from apps.control_api.errors import render_error

        request = Request(scope, receive)
        response = render_error(request, ValidationError("request_too_large", status_code=413))
        await response(scope, receive, send)


__all__ = [
    "REQUEST_ID_HEADER",
    "BodyLimitMiddleware",
    "ErrorClass",
    "RequestContextMiddleware",
    "body_limit_for",
]
