from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from apps.api.errors import error_response
from graphrec_core.auth.audit import record_public_login_denial
from graphrec_core.registration.audit import record_public_registration_denial
from graphrec_core.settings import Settings

MULTIPART_PATHS = frozenset({"/v1/datasets/upload"})


class ContractMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.settings = settings

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        correlation_id = self._correlation_id(request.headers.get("X-Correlation-ID"))
        request.state.correlation_id = correlation_id

        if request.url.path.startswith("/v1"):
            rejection = self._validate_contract_headers(request, correlation_id)
            if rejection is not None:
                if request.url.path == "/v1/tenants":
                    record_public_registration_denial(
                        event_type="registration_contract_denied",
                        correlation_id=correlation_id,
                        source=request.client.host if request.client else "unknown",
                        detail={"reason": "header_or_body_bound"},
                    )
                elif request.url.path == "/v1/auth/login":
                    record_public_login_denial(
                        event_type="login_contract_denied",
                        correlation_id=correlation_id,
                        source=request.client.host if request.client else "unknown",
                        detail={"reason": "header_or_body_bound"},
                    )
                return rejection

        response = await call_next(request)
        response.headers["X-Correlation-ID"] = str(correlation_id)
        return response

    def _validate_contract_headers(self, request: Request, correlation_id: UUID) -> Response | None:
        accept = request.headers.get("Accept")
        if accept and "application/json" not in accept.lower() and "*/*" not in accept:
            return error_response(
                correlation_id=correlation_id,
                status_code=400,
                code="malformed_request",
                message="Accept must permit application/json",
            )

        is_upload = request.url.path in MULTIPART_PATHS
        content_length = request.headers.get("Content-Length")
        size = 0
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                size = -1
            if size < 0:
                return error_response(
                    correlation_id=correlation_id,
                    status_code=400,
                    code="malformed_request",
                    message="Content-Length is invalid",
                )

        if request.method in {"POST", "PUT", "PATCH"}:
            content_type = request.headers.get("Content-Type", "").lower()
            # Action endpoints such as ``:activate`` or ``:disable`` carry no body, and
            # the console sends them without a Content-Type; only real bodies must be JSON.
            has_body = size > 0 or "transfer-encoding" in request.headers
            if is_upload:
                if not content_type.startswith("multipart/form-data"):
                    return error_response(
                        correlation_id=correlation_id,
                        status_code=400,
                        code="malformed_request",
                        message="Content-Type must be multipart/form-data",
                    )
            elif has_body and content_type != "application/json":
                return error_response(
                    correlation_id=correlation_id,
                    status_code=400,
                    code="malformed_request",
                    message="Content-Type must be application/json",
                )

        # Dataset files legitimately exceed the 16 KiB JSON limit.
        limit = (
            self.settings.max_upload_body_bytes
            if is_upload
            else self.settings.max_request_body_bytes
        )
        if size > limit:
            return error_response(
                correlation_id=correlation_id,
                status_code=413,
                code="payload_too_large",
                message="The request body exceeds the configured limit",
            )
        return None

    @staticmethod
    def _correlation_id(raw: str | None) -> UUID:
        if raw:
            try:
                return UUID(raw)
            except ValueError:
                pass
        return uuid4()
