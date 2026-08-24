"""The ASGI middleware that measures a request.

Raw ASGI rather than `BaseHTTPMiddleware`, for the same reason
`RequestContextMiddleware` is: `BaseHTTPMiddleware` runs the handler in a
separate task, and a timing taken around that task measures the wrong thing when
the response streams.

**The `route` label is the route template, never the request path.** A path
label on `/v1/products/{product_id}` would create one Prometheus series per
product — the classic cardinality bomb, and here it would also copy product and
tenant identifiers into a store that has no retention policy for them. FastAPI
puts the matched route in the scope, so the template is available for free; a
request that matched nothing is labelled `<unmatched>` rather than being dropped,
because a spike of 404s against invented paths is a scan and is worth seeing.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from graphrec.observability.metrics import HTTP_DURATION, HTTP_IN_FLIGHT, HTTP_REQUESTS

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: What a request that matched no route is labelled. One series for all of them.
UNMATCHED = "<unmatched>"


def route_label(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED


class MetricsMiddleware:
    """Count and time every HTTP request this process serves."""

    def __init__(self, app: ASGIApp, *, app_name: str) -> None:
        self.app = app
        self.app_name = app_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        started = time.perf_counter()
        # The status is captured from the response start message rather than
        # returned by the call, because an ASGI app returns nothing. `500` is
        # the default so that a handler which raises before sending anything is
        # counted as the failure it is, instead of vanishing from the count.
        status = 500

        async def observe(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        in_flight = HTTP_IN_FLIGHT.labels(app=self.app_name)
        in_flight.inc()
        try:
            await self.app(scope, receive, observe)
        finally:
            in_flight.dec()
            # Read after the call: the router populates `scope["route"]` while
            # handling, so asking before would label everything `<unmatched>`.
            route = route_label(scope)
            HTTP_DURATION.labels(app=self.app_name, method=method, route=route).observe(
                time.perf_counter() - started
            )
            HTTP_REQUESTS.labels(
                app=self.app_name, method=method, route=route, status=str(status)
            ).inc()
