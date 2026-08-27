"""Turning Pydantic's rejection into this package's, so callers write one `except`.

A caller should not need to know whether a bound was checked here or at the
server: `top_n=500` is the same mistake either way, and making them catch
`pydantic.ValidationError` for one and `graphrec_sdk.ValidationError` for the
other means every integration writes a tuple in its `except` clause or misses
one of them.

`reference` is `None` on everything built here: no request was made, so no
application assigned a trace id, and inventing one would produce something
support cannot find.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from .errors import FieldError, ValidationError

M = TypeVar("M", bound=BaseModel)


def _path(location: tuple[int | str, ...]) -> str:
    """`("events", 3, "event_id")` -> `events[3].event_id`, as the server writes it."""
    rendered = ""
    for part in location:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}" if rendered else str(part)
    return rendered


def build(model: type[M], what: str, **fields: Any) -> M:
    """Construct a request model, or raise this package's `ValidationError`."""
    try:
        return model(**fields)
    except PydanticValidationError as exc:
        field_errors = [
            FieldError(_path(error["loc"]), str(error["msg"])) for error in exc.errors()
        ]
        first = field_errors[0] if field_errors else FieldError("", "is not valid")
        raise ValidationError(
            f"{what} is not valid: {first.field} {first.reason}.",
            code="invalid_request",
            error_class="validation",
            reason=f"{what} is not valid.",
            reference=None,
            field_errors=field_errors,
        ) from exc


def parse(model: type[M], payload: object) -> M:
    """Decode a response.

    A response that will not parse is not the caller's mistake, so it is an
    `InternalError` rather than a `ValidationError` — the request was fine and
    something upstream sent a shape this version does not know. Response models
    ignore unknown fields, so this only fires when a *known* field is missing or
    the wrong type, which is a contract break rather than an extension.
    """
    from .errors import InternalError

    try:
        return model.model_validate(payload)
    except PydanticValidationError as exc:
        raise InternalError(
            f"The server's response did not match the expected shape for {model.__name__}. "
            "This is a client/server version mismatch rather than a problem with your request.",
            code="response_shape_mismatch",
            error_class="internal",
            reason="The response could not be decoded.",
            reference=None,
            retryable=False,
        ) from exc
