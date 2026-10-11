"""A-18: bound request bodies that arrive without Content-Length.

``ContractMiddleware`` rejects oversized bodies from their Content-Length. A
chunked request has none, so this ASGI middleware buffers such a body up to the
route's limit and answers 413 as soon as it is exceeded, before any route reads it.
"""
from __future__ import annotations

from uuid import uuid4

from apps.api.errors import error_response
from graphrec_core.settings import Settings

from apps.api.middleware import BULK_JSON_PATHS, MULTIPART_PATHS


class BodyLimitMiddleware:
    def __init__(self, app, *, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.settings = settings

    def _limit(self, path: str) -> int:
        if path in MULTIPART_PATHS:
            return self.settings.max_upload_body_bytes
        if path in BULK_JSON_PATHS:
            return self.settings.max_bulk_body_bytes
        return self.settings.max_request_body_bytes

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http" or not scope["path"].startswith("/v1"):
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        if b"content-length" in headers or scope["method"] in {"GET", "HEAD", "DELETE", "OPTIONS"}:
            return await self.app(scope, receive, send)
        limit = self._limit(scope["path"])
        chunks: list[bytes] = []
        size = 0
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > limit:
                response = error_response(
                    correlation_id=uuid4(), status_code=413, code="payload_too_large",
                    message="The request body exceeds the configured limit",
                )
                return await response(scope, receive, send)
            chunks.append(body)
            more = message.get("more_body", False)
        buffered = b"".join(chunks)
        delivered = False

        async def replay():  # type: ignore[no-untyped-def]
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
