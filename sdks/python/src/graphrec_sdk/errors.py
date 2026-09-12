"""Exception hierarchy for the GraphRec SDK.

Every exception raised by the SDK derives from :class:`GraphRecError`.

GraphRec returns failures in a stable envelope::

    {"error": {"code": "rate_limit_exceeded", "message": "...",
               "correlation_id": "…", "retryable": true,
               "retry_after_seconds": 12, "details": {...}}}

:func:`error_from_response` maps that envelope onto the most specific
subclass so callers can write ``except NotFoundError:`` instead of inspecting
status codes. The ``correlation_id`` on every :class:`APIError` matches the
``X-Correlation-ID`` header GraphRec logs, which makes support requests easy
to trace.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Type

import httpx

__all__ = [
    "APIConnectionError",
    "APIError",
    "APIResponseValidationError",
    "APIStatusError",
    "APITimeoutError",
    "AuthenticationError",
    "ConfigurationError",
    "ConflictError",
    "DuplicateResourceError",
    "FieldError",
    "GraphRecError",
    "IdempotencyConflictError",
    "InputValidationError",
    "InternalServerError",
    "MalformedRequestError",
    "NotFoundError",
    "PayloadTooLargeError",
    "PermissionDeniedError",
    "QuotaExceededError",
    "RateLimitError",
    "RequestValidationError",
    "ServiceUnavailableError",
    "StateConflictError",
    "TokenExpiredError",
    "WaitTimeoutError",
    "error_from_response",
]


class GraphRecError(Exception):
    """Base class for every error raised by the SDK."""


class ConfigurationError(GraphRecError):
    """The client is not configured for the requested call (e.g. missing credentials)."""


class InputValidationError(GraphRecError, ValueError):
    """Arguments failed client-side validation before any request was sent."""

    def __init__(self, message: str, *, errors: Optional[List[Dict[str, Any]]] = None) -> None:
        super().__init__(message)
        self.errors: List[Dict[str, Any]] = errors or []


class WaitTimeoutError(GraphRecError, TimeoutError):
    """A polling helper such as ``training_jobs.wait()`` gave up before completion."""


class APIError(GraphRecError):
    """A request reached (or tried to reach) the GraphRec API and failed."""

    def __init__(
        self,
        message: str,
        *,
        request: Optional[httpx.Request] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.request = request
        self.correlation_id = correlation_id


class APIConnectionError(APIError):
    """The API could not be reached (DNS, refused connection, TLS, reset...)."""

    def __init__(
        self,
        message: str = "Could not connect to the GraphRec API",
        *,
        request: Optional[httpx.Request] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        super().__init__(message, request=request, correlation_id=correlation_id)


class APITimeoutError(APIConnectionError):
    """The request timed out."""

    def __init__(
        self,
        message: str = "The GraphRec API request timed out",
        *,
        request: Optional[httpx.Request] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        super().__init__(message, request=request, correlation_id=correlation_id)


class FieldError:
    """One invalid field reported by a ``validation_failed`` response."""

    __slots__ = ("field", "message")

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message

    def __repr__(self) -> str:
        return f"FieldError(field={self.field!r}, message={self.message!r})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FieldError)
            and other.field == self.field
            and other.message == self.message
        )

    def __hash__(self) -> int:
        return hash((self.field, self.message))


class APIStatusError(APIError):
    """The API answered with a non-success HTTP status."""

    def __init__(
        self,
        message: str,
        *,
        response: httpx.Response,
        code: str,
        correlation_id: Optional[str] = None,
        retryable: bool = False,
        retry_after_seconds: Optional[float] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message, request=response.request, correlation_id=correlation_id)
        self.response = response
        self.status_code = response.status_code
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.details: Dict[str, Any] = dict(details or {})

    def __str__(self) -> str:
        suffix = f" (correlation_id={self.correlation_id})" if self.correlation_id else ""
        return f"{self.status_code} {self.code}: {self.message}{suffix}"


class MalformedRequestError(APIStatusError):
    """HTTP 400 ``malformed_request`` - headers or JSON body were rejected."""


class AuthenticationError(APIStatusError):
    """HTTP 401 - the credential is missing, invalid, revoked or expired."""


class TokenExpiredError(AuthenticationError):
    """HTTP 401 ``token_expired`` - the bearer access token has expired."""


class PermissionDeniedError(APIStatusError):
    """HTTP 403 ``insufficient_scope`` - the credential lacks a required scope."""


class NotFoundError(APIStatusError):
    """HTTP 404 ``resource_not_found``."""


class ConflictError(APIStatusError):
    """HTTP 409 - base class for conflicts."""


class DuplicateResourceError(ConflictError):
    """HTTP 409 ``duplicate_resource`` - e.g. an API-key name or version tag is taken."""


class IdempotencyConflictError(ConflictError):
    """HTTP 409 ``idempotency_conflict`` - an Idempotency-Key was reused with a new body."""


class StateConflictError(ConflictError):
    """HTTP 409 ``state_conflict`` / ``conflict`` - the resource is in the wrong state."""


class PayloadTooLargeError(APIStatusError):
    """HTTP 413 ``payload_too_large`` - the body exceeded the server's limit."""


class RequestValidationError(APIStatusError):
    """HTTP 422 ``validation_failed`` - one or more fields are invalid."""

    @property
    def field_errors(self) -> List[FieldError]:
        fields = self.details.get("fields")
        if not isinstance(fields, list):
            return []
        return [
            FieldError(str(item.get("field", "")), str(item.get("message", "")))
            for item in fields
            if isinstance(item, Mapping)
        ]


class RateLimitError(APIStatusError):
    """HTTP 429 ``rate_limit_exceeded`` - retry after ``retry_after_seconds``."""


class QuotaExceededError(APIStatusError):
    """HTTP 429 ``quota_exceeded`` - a plan or tenant quota is exhausted (not retryable)."""


class InternalServerError(APIStatusError):
    """HTTP 5xx without a more specific code."""


class ServiceUnavailableError(InternalServerError):
    """HTTP 503 ``service_unavailable`` - a dependency is temporarily unavailable."""


class APIResponseValidationError(APIError):
    """A success response did not match the schema the SDK expects."""

    def __init__(
        self,
        message: str,
        *,
        response: httpx.Response,
        body: Any,
        correlation_id: Optional[str] = None,
    ) -> None:
        super().__init__(message, request=response.request, correlation_id=correlation_id)
        self.response = response
        self.status_code = response.status_code
        self.body = body


_CODE_MAP: Dict[str, Type[APIStatusError]] = {
    "malformed_request": MalformedRequestError,
    "authentication_failed": AuthenticationError,
    "invalid_setup_token": AuthenticationError,
    "token_expired": TokenExpiredError,
    "insufficient_scope": PermissionDeniedError,
    "resource_not_found": NotFoundError,
    "duplicate_resource": DuplicateResourceError,
    "idempotency_conflict": IdempotencyConflictError,
    "state_conflict": StateConflictError,
    "conflict": StateConflictError,
    "payload_too_large": PayloadTooLargeError,
    "validation_failed": RequestValidationError,
    "rate_limit_exceeded": RateLimitError,
    "quota_exceeded": QuotaExceededError,
    "service_unavailable": ServiceUnavailableError,
}

_STATUS_MAP: Dict[int, Type[APIStatusError]] = {
    400: MalformedRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    413: PayloadTooLargeError,
    422: RequestValidationError,
    429: RateLimitError,
    503: ServiceUnavailableError,
}


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def error_from_response(response: httpx.Response) -> APIStatusError:
    """Build the most specific :class:`APIStatusError` for an error response."""

    envelope: Mapping[str, Any] = {}
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, Mapping):
        candidate = body.get("error")
        if isinstance(candidate, Mapping):
            envelope = candidate

    status = response.status_code
    code = str(envelope.get("code") or f"http_{status}")
    message = str(
        envelope.get("message") or response.reason_phrase or f"HTTP {status} from GraphRec API"
    )
    correlation_id = envelope.get("correlation_id") or response.headers.get("X-Correlation-ID")
    retry_after = envelope.get("retry_after_seconds")
    retry_after_seconds = (
        float(retry_after)
        if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool)
        else _parse_retry_after(response.headers.get("Retry-After"))
    )
    retryable_raw = envelope.get("retryable")
    retryable = bool(retryable_raw) if isinstance(retryable_raw, bool) else status in {429, 503}
    if code == "quota_exceeded":
        retryable = False
    details = envelope.get("details")

    error_cls = _CODE_MAP.get(code)
    if error_cls is None:
        error_cls = _STATUS_MAP.get(status)
    if error_cls is None:
        error_cls = InternalServerError if status >= 500 else APIStatusError

    return error_cls(
        message,
        response=response,
        code=code,
        correlation_id=str(correlation_id) if correlation_id else None,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
        details=details if isinstance(details, Mapping) else None,
    )
