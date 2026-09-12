from __future__ import annotations

from typing import Any, Mapping, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

from .errors import InputValidationError

M = TypeVar("M", bound=BaseModel)


def coerce_input(model: Type[M], value: Union[M, Mapping[str, Any]]) -> M:
    """Validate a dict (or pass through a model instance) with SDK-side constraints."""

    if isinstance(value, model):
        return value
    if isinstance(value, BaseModel):
        value = value.model_dump()
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise InputValidationError(
            f"Invalid {model.__name__}: {exc}",
            errors=[dict(error) for error in exc.errors(include_url=False)],
        ) from exc


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)
