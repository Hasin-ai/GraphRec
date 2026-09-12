from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from graphrec_core.settings import get_settings


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not value:
            raise ValueError("Password must not be empty")
        if len(value) > get_settings().max_password_length:
            raise ValueError("Password is too long")
        return value


class SetupPasswordRequest(BaseModel):
    """Activate an invited account with its one-time setup token."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    setup_token: str = Field(min_length=16, max_length=256)
    password: str
    # Optional confirmation; when supplied it must match the invited account.
    email: EmailStr | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        return str(value).lower() if value is not None else None

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(value) > get_settings().max_password_length:
            raise ValueError("Password is too long")
        return value


class AuthTokenPair(BaseModel):
    access_token: str
    token_type: Literal["Bearer"]
    expires_in: int
    refresh_token: str
    user_role: Literal["tenant_administrator", "tenant_developer", "platform_administrator"]
    scopes: list[str]
