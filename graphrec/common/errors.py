"""The error envelope — every failure, without exception.

`class`, `reason` and `reference` are published to tenants by the console's
/integration page (dc.html L1163-1193). They are a public contract: do not rename
them. `code` and `field_errors` are additive and safe to extend.

Nothing that reaches a client through this module may carry a secret, a raw event
payload, a password, a token or another tenant's identifier (NR-NF-06). The
`reason` always comes from the vetted catalogue in `error_copy`, never from an
exception's own string.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field


class ErrorClass(StrEnum):
    """The seven classes. The first four are published on /integration."""

    VALIDATION = "validation"
    CONFLICT = "conflict"
    LIMIT = "limit"
    UNAVAILABLE = "unavailable"
    AUTH = "auth"
    NOT_FOUND = "not_found"
    INTERNAL = "internal"


#: Default HTTP status per class. An individual error may override it — a
#: `validation` error is 422 normally but 413 when a bounded collection is
#: oversize, and both are the same class to the console.
DEFAULT_STATUS: dict[ErrorClass, int] = {
    ErrorClass.VALIDATION: 422,
    ErrorClass.CONFLICT: 409,
    ErrorClass.LIMIT: 429,
    ErrorClass.UNAVAILABLE: 503,
    ErrorClass.AUTH: 401,
    ErrorClass.NOT_FOUND: 404,
    ErrorClass.INTERNAL: 500,
}


class FieldError(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    reason: str


class ErrorBody(BaseModel):
    """The `error` object. Serialised with `class`, which is a Python keyword."""

    model_config = ConfigDict(populate_by_name=True)

    error_class: ErrorClass = Field(serialization_alias="class")
    code: str
    reason: str
    reference: str
    field_errors: list[FieldError] = Field(default_factory=list)
    retryable: bool = False
    retry_after_seconds: int | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class GraphRecError(Exception):
    """Base for every failure that should reach a client as an envelope.

    Carries no message of its own: the reason is resolved from the copy
    catalogue by `code` at render time, so that the console and the API can never
    disagree about what a given failure says.
    """

    error_class: ErrorClass = ErrorClass.INTERNAL
    code: str = "internal_error"
    status_code: int | None = None
    retryable: bool = False

    def __init__(
        self,
        code: str | None = None,
        *,
        error_class: ErrorClass | None = None,
        reason: str | None = None,
        field_errors: list[FieldError] | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
        retry_after_seconds: int | None = None,
        copy_args: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or self.code
        self.error_class = error_class or self.error_class
        self.status_code = status_code or self.status_code or DEFAULT_STATUS[self.error_class]
        self.retryable = self.retryable if retryable is None else retryable
        self.retry_after_seconds = retry_after_seconds
        self.field_errors = field_errors or []
        self.copy_args = copy_args or {}
        self._explicit_reason = reason
        super().__init__(self.code)

    def reason(self) -> str:
        """Resolve user-facing copy. Imported lazily to keep the layering acyclic."""
        if self._explicit_reason is not None:
            return self._explicit_reason
        from graphrec.common.error_copy import resolve_copy

        return resolve_copy(self.code, **self.copy_args)

    def to_body(self, reference: str) -> ErrorBody:
        return ErrorBody(
            error_class=self.error_class,
            code=self.code,
            reason=self.reason(),
            reference=reference,
            field_errors=self.field_errors,
            retryable=self.retryable,
            retry_after_seconds=self.retry_after_seconds,
        )

    def with_field(self, field: str, reason: str) -> Self:
        self.field_errors.append(FieldError(field=field, reason=reason))
        return self


class ValidationError(GraphRecError):
    error_class = ErrorClass.VALIDATION
    code = "invalid_request"


class ConflictError(GraphRecError):
    """409. The console keeps the form filled — the user has something to reconcile."""

    error_class = ErrorClass.CONFLICT
    code = "conflict"


class LimitError(GraphRecError):
    """429. The message must name the numbers; the console renders them."""

    error_class = ErrorClass.LIMIT
    code = "limit_exhausted"


class UnavailableError(GraphRecError):
    error_class = ErrorClass.UNAVAILABLE
    code = "service_unavailable"
    retryable = True


class AuthError(GraphRecError):
    error_class = ErrorClass.AUTH
    code = "unauthenticated"


class NotFoundError(GraphRecError):
    """404 — and it never names the resource type.

    A foreign resource and a missing one must be indistinguishable (gate 4). Any
    detail here would confirm existence, which is itself a cross-tenant leak.
    """

    error_class = ErrorClass.NOT_FOUND
    code = "not_found"


class InternalError(GraphRecError):
    error_class = ErrorClass.INTERNAL
    code = "internal_error"
    retryable = True
