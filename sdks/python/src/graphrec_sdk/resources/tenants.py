from __future__ import annotations

from typing import Dict, Optional, cast

from .._ids import new_idempotency_key
from ..models.auth import AuthTokenPair, TenantRegistration
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncAuthentication", "AsyncTenants", "Authentication", "Tenants"]


class Tenants(SyncResource):
    def register(
        self, *, name: str, admin_email: str, idempotency_key: Optional[str] = None
    ) -> TenantRegistration:
        """Register a business as a tenant with its first administrator.

        ``POST /v1/tenants`` - public. Safe to retry: the ``Idempotency-Key``
        (generated when omitted) makes repeated submissions return the original
        tenant. Pass your own key to stay idempotent across process restarts.

        The result carries a one-time ``setup_token`` that activates the
        administrator through :meth:`Authentication.setup_password`. Keep it
        secret. It is returned only once: a replayed registration has
        ``setup_token=None``, and an operator has to issue a new one.
        """

        return cast(
            TenantRegistration,
            self._client.request(
                "tenants.register",
                json={"name": name, "admin_email": admin_email},
                idempotency_key=idempotency_key or new_idempotency_key(),
                cast_to=TenantRegistration,
            ),
        )


class AsyncTenants(AsyncResource):
    async def register(
        self, *, name: str, admin_email: str, idempotency_key: Optional[str] = None
    ) -> TenantRegistration:
        """Async variant of :meth:`Tenants.register`."""

        return cast(
            TenantRegistration,
            await self._client.request(
                "tenants.register",
                json={"name": name, "admin_email": admin_email},
                idempotency_key=idempotency_key or new_idempotency_key(),
                cast_to=TenantRegistration,
            ),
        )


class Authentication(SyncResource):
    def login(self, *, email: str, password: str) -> AuthTokenPair:
        """Exchange a tenant user's email and password for tokens (``POST /v1/auth/login``).

        Tip: create the client with ``email=``/``password=`` instead and the SDK
        will log in and re-login automatically when the 15-minute token expires.
        """

        return cast(
            AuthTokenPair,
            self._client.request(
                "auth.login", json={"email": email, "password": password}, cast_to=AuthTokenPair
            ),
        )

    def setup_password(
        self, *, setup_token: str, password: str, email: Optional[str] = None
    ) -> AuthTokenPair:
        """Activate an invited account with its one-time setup token and choose a password.

        ``POST /v1/auth/setup-password`` - ``setup_token`` comes from
        :attr:`TenantRegistration.setup_token` (or an operator reissue). It can be
        used once, expires, and only activates accounts that are still invited.
        Pass ``email`` to have the server confirm the token belongs to that
        address. Passwords must be at least 8 characters. Every rejection is an
        :class:`AuthenticationError` with code ``invalid_setup_token``.
        """

        return cast(
            AuthTokenPair,
            self._client.request(
                "auth.setup_password",
                json=_setup_body(setup_token, password, email),
                cast_to=AuthTokenPair,
            ),
        )


class AsyncAuthentication(AsyncResource):
    async def login(self, *, email: str, password: str) -> AuthTokenPair:
        """Async variant of :meth:`Authentication.login`."""

        return cast(
            AuthTokenPair,
            await self._client.request(
                "auth.login", json={"email": email, "password": password}, cast_to=AuthTokenPair
            ),
        )

    async def setup_password(
        self, *, setup_token: str, password: str, email: Optional[str] = None
    ) -> AuthTokenPair:
        """Async variant of :meth:`Authentication.setup_password`."""

        return cast(
            AuthTokenPair,
            await self._client.request(
                "auth.setup_password",
                json=_setup_body(setup_token, password, email),
                cast_to=AuthTokenPair,
            ),
        )


def _setup_body(setup_token: str, password: str, email: Optional[str]) -> Dict[str, str]:
    body = {"setup_token": setup_token, "password": password}
    if email is not None:
        body["email"] = email
    return body
