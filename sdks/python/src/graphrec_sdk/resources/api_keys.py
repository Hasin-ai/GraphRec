from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Union, cast
from uuid import UUID

from .._validation import enum_value
from ..errors import InputValidationError
from ..models.api_keys import ApiKey, ApiKeyList, ApiKeyWithSecret
from ..scopes import Scope
from ._base import AsyncResource, SyncResource

__all__ = ["ApiKeys", "AsyncApiKeys"]

ScopeLike = Union[Scope, str]


def _create_body(
    name: str, scopes: Sequence[ScopeLike], expires_at: Optional[datetime]
) -> Dict[str, Any]:
    values = [str(enum_value(scope)) for scope in scopes]
    if not name.strip():
        raise InputValidationError("API-key name must not be blank")
    if not values:
        raise InputValidationError("An API key needs at least one scope")
    if len(values) != len(set(values)):
        raise InputValidationError("API-key scopes must be unique")
    if expires_at is not None and (expires_at.tzinfo is None or expires_at.utcoffset() is None):
        raise InputValidationError(
            "expires_at must be timezone-aware (e.g. datetime.now(timezone.utc))"
        )
    body: Dict[str, Any] = {"name": name, "scopes": values}
    if expires_at is not None:
        body["expires_at"] = expires_at
    return body


def _rotate_body(reason: str, grace_period_seconds: int) -> Dict[str, Any]:
    if not reason.strip():
        raise InputValidationError("A rotation reason is required")
    if not 0 <= grace_period_seconds <= 86_400:
        raise InputValidationError("grace_period_seconds must be between 0 and 86400")
    return {"grace_period_seconds": grace_period_seconds, "reason": reason}


class ApiKeys(SyncResource):
    """Scoped server credentials. Requires a tenant user's bearer token (``keys:write``)."""

    def list(self) -> ApiKeyList:
        """``GET /v1/api-keys`` - redacted list (secrets are never returned)."""

        return cast(ApiKeyList, self._client.request("api_keys.list", cast_to=ApiKeyList))

    def get(self, key_id: Union[str, UUID]) -> ApiKey:
        """``GET /v1/api-keys/{key_id}``."""

        return cast(
            ApiKey,
            self._client.request("api_keys.get", path_params={"key_id": key_id}, cast_to=ApiKey),
        )

    def create(
        self,
        *,
        name: str,
        scopes: Sequence[ScopeLike],
        expires_at: Optional[datetime] = None,
    ) -> ApiKeyWithSecret:
        """Create a key. ``secret`` is only returned now - store it securely.

        ``POST /v1/api-keys``. Not retried after ambiguous network failures
        because a retry could create a second key; names are unique per tenant.
        """

        return cast(
            ApiKeyWithSecret,
            self._client.request(
                "api_keys.create",
                json=_create_body(name, scopes, expires_at),
                cast_to=ApiKeyWithSecret,
            ),
        )

    def rotate(
        self, key_id: Union[str, UUID], *, reason: str, grace_period_seconds: int = 0
    ) -> ApiKeyWithSecret:
        """Issue a new secret. The old one keeps working for ``grace_period_seconds`` (max 1 day).

        ``POST /v1/api-keys/{key_id}/rotate``.
        """

        return cast(
            ApiKeyWithSecret,
            self._client.request(
                "api_keys.rotate",
                path_params={"key_id": key_id},
                json=_rotate_body(reason, grace_period_seconds),
                cast_to=ApiKeyWithSecret,
            ),
        )

    def revoke(self, key_id: Union[str, UUID]) -> ApiKey:
        """Revoke immediately (idempotent). ``DELETE /v1/api-keys/{key_id}``."""

        return cast(
            ApiKey,
            self._client.request("api_keys.revoke", path_params={"key_id": key_id}, cast_to=ApiKey),
        )


class AsyncApiKeys(AsyncResource):
    async def list(self) -> ApiKeyList:
        """Async variant of :meth:`ApiKeys.list`."""

        return cast(ApiKeyList, await self._client.request("api_keys.list", cast_to=ApiKeyList))

    async def get(self, key_id: Union[str, UUID]) -> ApiKey:
        """Async variant of :meth:`ApiKeys.get`."""

        return cast(
            ApiKey,
            await self._client.request(
                "api_keys.get", path_params={"key_id": key_id}, cast_to=ApiKey
            ),
        )

    async def create(
        self,
        *,
        name: str,
        scopes: Sequence[ScopeLike],
        expires_at: Optional[datetime] = None,
    ) -> ApiKeyWithSecret:
        """Async variant of :meth:`ApiKeys.create`."""

        return cast(
            ApiKeyWithSecret,
            await self._client.request(
                "api_keys.create",
                json=_create_body(name, scopes, expires_at),
                cast_to=ApiKeyWithSecret,
            ),
        )

    async def rotate(
        self, key_id: Union[str, UUID], *, reason: str, grace_period_seconds: int = 0
    ) -> ApiKeyWithSecret:
        """Async variant of :meth:`ApiKeys.rotate`."""

        return cast(
            ApiKeyWithSecret,
            await self._client.request(
                "api_keys.rotate",
                path_params={"key_id": key_id},
                json=_rotate_body(reason, grace_period_seconds),
                cast_to=ApiKeyWithSecret,
            ),
        )

    async def revoke(self, key_id: Union[str, UUID]) -> ApiKey:
        """Async variant of :meth:`ApiKeys.revoke`."""

        return cast(
            ApiKey,
            await self._client.request(
                "api_keys.revoke", path_params={"key_id": key_id}, cast_to=ApiKey
            ),
        )
