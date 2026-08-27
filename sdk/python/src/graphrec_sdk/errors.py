"""The error hierarchy, one class per way a call can fail.

The reasoning is the TypeScript SDK's, and the two are kept deliberately
parallel: every failure the API produces has one shape (`graphrec/common/errors.py`
renders it, `graphrec/http/errors.py` translates FastAPI's own 422s and
Starlette's bare `HTTPException`s into it), so there is exactly one body to
parse — and what an SDK adds is a *type* per failure, because `except
GraphRecError` alone means every caller re-implements the same
`if err.status == 429` ladder and gets one rung of it wrong.

Two decisions carry over unchanged.

**The subclass is chosen by `status` and `class` together, never by `class`
alone.** A 403 arrives as ``class: "auth"`` — `ForbiddenError` sets
``error_class = ErrorClass.AUTH`` with ``status_code = 403``. Switching on the
class alone cannot tell "we do not know who you are" from "we know, and no",
which are the two failures in this API with the most different remedies.

**`code` is a plain `str`, not an enum.** There are 87 of them in
`graphrec/common/error_copy.py` and the contract says `code` is additive. An
enum would make a value the server may legally add into one this package calls
impossible.

Two names differ from the TypeScript SDK, and only because Python has builtins
of the same name. `TimeoutError` is `APITimeoutError` here and `PermissionError`
is `PermissionDeniedError`; `from graphrec_sdk import TimeoutError` would
otherwise shadow the builtin in the importing module and change the meaning of
`except TimeoutError` for code that has nothing to do with this SDK.
"""

from __future__ import annotations

from typing import Any, Literal

#: The seven the server can emit. There is no `forbidden`; a 403 is `auth`.
ErrorClass = Literal[
    "validation",
    "conflict",
    "limit",
    "unavailable",
    "auth",
    "not_found",
    "internal",
]


class FieldError:
    """One entry of `field_errors`. A path and a reason, never the value."""

    __slots__ = ("field", "reason")

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason

    def __repr__(self) -> str:
        return f"FieldError(field={self.field!r}, reason={self.reason!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FieldError):
            return NotImplemented
        return (self.field, self.reason) == (other.field, other.reason)

    def __hash__(self) -> int:
        return hash((self.field, self.reason))


class GraphRecError(Exception):
    """Base for everything this SDK raises."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        error_class: ErrorClass,
        reason: str,
        reference: str | None,
        field_errors: list[FieldError] | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        #: The stable machine-readable name of the failure. Branch on this.
        self.code = code
        self.error_class = error_class
        #: Server-authored copy. Safe to show a user; it is vetted for that.
        self.reason = reason
        #: The traceable id — the only thing that leads to this request's log
        #: lines. `None` only on a `TransportError`, which never reached an
        #: application that could assign one.
        self.reference = reference
        self.field_errors = field_errors or []
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.status = status
        #: `X-Request-Id` off the response; equals `reference` when both exist.
        self.request_id = request_id

    @property
    def is_transient(self) -> bool:
        """Whether re-sending the *same* request could succeed.

        Both halves matter. `retryable` is the server saying the condition is
        transient — `UnavailableError` and `InternalError` set it. A present
        `retry_after_seconds` is the server naming a wait, which the rate
        limiter does even though it reports ``retryable: False``, because the
        request itself was never wrong. A quota refusal has neither, and that is
        the distinction this property exists to preserve: see
        `QuotaExhaustedError`.

        Whether it is *safe* to retry is a different question, answered by the
        caller having supplied an idempotency identifier. The transport asks
        both.
        """
        return self.retryable or self.retry_after_seconds is not None

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, status={self.status!r}, "
            f"reference={self.reference!r})"
        )


class ValidationError(GraphRecError):
    """422, and 413 when a bounded collection is oversize. Never retried."""


class ConflictError(GraphRecError):
    """409. Something in the tenant's state has to be reconciled first."""


class LimitError(GraphRecError):
    """429. Never raised directly — see the two subclasses."""


class RateLimitedError(LimitError):
    """429 `rate_limited`.

    Too many requests in the window; `retry_after_seconds` is the distance to
    the window edge and waiting it out works.
    """


class QuotaExhaustedError(LimitError):
    """429 `*_quota_exhausted`. The plan allowance for the period is spent.

    Also a 429, also ``class: "limit"``, and the opposite remedy: there is no
    `Retry-After` because waiting does not help — the quota resets at the end of
    the billing period, and the fix is a plan change or an override. A client
    that folded this into `RateLimitedError` would retry it until the period
    rolled.
    """


class UnavailableError(GraphRecError):
    """503. Transient by construction — `retryable` is true on the server class."""


class AuthenticationError(GraphRecError):
    """401. The credential is absent, malformed, revoked or not ours."""


class PermissionDeniedError(AuthenticationError):
    """403. We know who you are and the answer is still no.

    Three codes reach here and they mean different things: `insufficient_scope`
    (mint a credential with the scope), `insufficient_role` (a person's session
    lacking the developer role) and `tenant_not_active` (the tenant is suspended
    and no credential will work until that is resolved).

    A subclass of `AuthenticationError` rather than a sibling, so that a caller
    who only wants "the credential did not work" writes one `except`.
    """


class NotFoundError(GraphRecError):
    """404, and it never names the resource — a foreign one and a missing one
    are one answer."""


class InternalError(GraphRecError):
    """500. Retryable, and the `reference` is what support needs."""


class TransportError(GraphRecError):
    """The request never got an answer: DNS, connect, TLS, socket.

    `reference` is `None` and says so, because no application assigned one. The
    message names TLS explicitly: both public edges pin ``protocols tls1.3``
    (`deploy/n1/Caddyfile`, `deploy/n3/Caddyfile`), so a runtime that cannot
    negotiate 1.3 fails the handshake with no status code to look up — and
    "connection error" is not a diagnosis anybody can act on.
    """

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="transport_error",
            error_class="unavailable",
            reason=message,
            reference=None,
            retryable=True,
        )


class APITimeoutError(GraphRecError):
    """The call's time budget ran out. Not retried — the budget is spent.

    Named `APITimeoutError` rather than `TimeoutError` because the latter is a
    builtin; see the module docstring.
    """

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="timeout",
            error_class="unavailable",
            reason=message,
            reference=None,
            retryable=False,
        )


class ConfigurationError(GraphRecError):
    """Bad SDK configuration, caught before a request is built.

    Never carries the credential: every message here describes the *shape* of
    what was wrong and does not quote the value, because a configuration error
    that echoes a credential puts it in the one place people paste most freely,
    which is a bug report.
    """

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="configuration_error",
            error_class="validation",
            reason=message,
            reference=None,
        )


#: Starlette raises bare `HTTPException`s for a few transport-level conditions
#: and `graphrec/http/errors.py` maps them onto classes on the way out. The same
#: map is kept here for the reverse case: a response that is not an envelope at
#: all — a proxy's 502 HTML, a 413 from Caddy's body ceiling before the
#: application saw the request — still has to become a typed error.
_STATUS_FALLBACK: dict[int, tuple[ErrorClass, str]] = {
    400: ("validation", "invalid_request"),
    401: ("auth", "unauthenticated"),
    403: ("auth", "insufficient_role"),
    404: ("not_found", "not_found"),
    405: ("validation", "invalid_request"),
    409: ("conflict", "conflict"),
    413: ("validation", "request_too_large"),
    422: ("validation", "invalid_request"),
    429: ("limit", "rate_limited"),
    500: ("internal", "internal_error"),
    502: ("unavailable", "service_unavailable"),
    503: ("unavailable", "service_unavailable"),
    504: ("unavailable", "service_unavailable"),
}


def _looks_like_envelope(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    body = payload.get("error")
    return (
        isinstance(body, dict)
        and isinstance(body.get("code"), str)
        and isinstance(body.get("class"), str)
    )


def _class_for(status: int, error_class: str, code: str) -> type[GraphRecError]:
    """Which class the envelope becomes. Status first, because 403 hides inside `auth`."""
    if status == 401:
        return AuthenticationError
    if status == 403:
        return PermissionDeniedError
    if error_class == "validation":
        return ValidationError
    if error_class == "conflict":
        return ConflictError
    if error_class == "limit":
        # Same status, same class, opposite remedies. See `QuotaExhaustedError`.
        if code == "rate_limited":
            return RateLimitedError
        if code.endswith("quota_exhausted"):
            return QuotaExhaustedError
        return LimitError
    if error_class == "unavailable":
        return UnavailableError
    if error_class == "auth":
        return AuthenticationError
    if error_class == "not_found":
        return NotFoundError
    if error_class == "internal":
        return InternalError
    return GraphRecError


def _summarise(reason: str, code: str, status: int, fields: list[FieldError]) -> str:
    """The message a stack trace will carry.

    `reason` is the server's copy, which is written for a person and is what a
    caller should print. For a validation failure it is deliberately general —
    "one or more fields were rejected" — and the part that says *which* lives in
    `field_errors`. A traceback that stops at the general half sends the reader
    back to the API to find out what they already had, so the paths are appended
    here. Three of them, then a count: this is a message, not a report, and the
    full list is on the exception.
    """
    head = reason or f"{code} ({status})"
    if not fields:
        return head
    shown = ", ".join(f"{item.field}: {item.reason}" for item in fields[:3])
    if len(fields) > 3:
        shown += f", and {len(fields) - 3} more"
    return f"{head} ({shown})"


def error_from(status: int, payload: object, request_id: str | None) -> GraphRecError:
    """Build the typed error for a non-2xx response.

    `request_id` comes from the `X-Request-Id` header, which
    `graphrec/http/middleware.py` sets on every response including ones that
    never reached a handler. It becomes `reference` when the body carries none,
    so a failure at the edge is still traceable.
    """
    if _looks_like_envelope(payload):
        body: dict[str, Any] = payload["error"]  # type: ignore[index]
        code = str(body["code"])
        error_class: ErrorClass = body["class"]
        cls = _class_for(status, error_class, code)
        reason = str(body.get("reason") or "")
        fields = [
            FieldError(str(item.get("field", "")), str(item.get("reason", "")))
            for item in body.get("field_errors") or []
        ]
        return cls(
            _summarise(reason, code, status, fields),
            code=code,
            error_class=error_class,
            reason=reason,
            reference=body.get("reference") or request_id,
            field_errors=fields,
            retryable=bool(body.get("retryable", False)),
            retry_after_seconds=body.get("retry_after_seconds"),
            status=status,
            request_id=request_id,
        )

    fallback_class, fallback_code = _STATUS_FALLBACK.get(status, ("internal", "internal_error"))
    cls = _class_for(status, fallback_class, fallback_code)
    return cls(
        f"The server answered {status} with a body this client could not read as "
        "an error envelope.",
        code=fallback_code,
        error_class=fallback_class,
        reason="",
        reference=request_id,
        retryable=fallback_class in ("unavailable", "internal"),
        status=status,
        request_id=request_id,
    )
