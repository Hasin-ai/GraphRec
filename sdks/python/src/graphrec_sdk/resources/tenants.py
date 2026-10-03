"""Tenant sign-up and tenant-user authentication (``/v1/tenants``, ``/v1/auth/*``)."""

from __future__ import annotations

from typing import Dict, Optional, cast

from .._ids import new_idempotency_key
from ..models.auth import AuthTokenPair, TenantRegistration
from ._base import AsyncResource, SyncResource

__all__ = ["AsyncAuthentication", "Authentication"]


def _register_body(name: str, admin_email: str) -> Dict[str, str]:
    return {"name": name, "admin_email": admin_email}


def _setup_body(
    setup_token: str, password: str, email: Optional[str], *, key: str = "setup_token"
) -> Dict[str, str]:
    body = {key: setup_token, "password": password}
    if email is not None:
        body["email"] = email
    return body


class Authentication(SyncResource):
    """Registration, sign-in, account setup/recovery and sign-out for tenant users."""

    def register(
        self, *, name: str, admin_email: str, idempotency_key: Optional[str] = None
    ) -> TenantRegistration:
        """Register a business as a tenant with its first administrator.

        ``POST /v1/tenants`` - public. Safe to retry: the ``Idempotency-Key``
        (generated when omitted) makes repeated submissions return the original
        tenant. Pass your own key to stay idempotent across process restarts.

        The result carries a one-time ``setup_token`` that activates the
        administrator through :meth:`setup_password`. Keep it secret. It is
        returned only once: a replayed registration has ``setup_token=None``.
        """

        return cast(
            TenantRegistration,
            self._client.request(
                "tenants.register",
                json=_register_body(name, admin_email),
                idempotency_key=idempotency_key or new_idempotency_key(),
                cast_to=TenantRegistration,
            ),
        )

    def login(self, *, email: str, password: str) -> AuthTokenPair:
        """Exchange a tenant user's email and password for tokens (``POST /v1/auth/login``).

        Tip: create the client with ``email=``/``password=`` instead and the SDK
        logs in, and logs in again when the 15-minute token expires.
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

        ``POST /v1/auth/setup-password`` - ``setup_token`` comes from a
        registration, an invitation or an operator reissue. It can be used once,
        expires, and only activates accounts that are still invited. Pass
        ``email`` to have the server confirm the token belongs to that address.
        Every rejection is an :class:`~graphrec_sdk.AuthenticationError`.
        """

        return cast(
            AuthTokenPair,
            self._client.request(
                "auth.setup_password",
                json=_setup_body(setup_token, password, email),
                cast_to=AuthTokenPair,
            ),
        )

    def recover_password(
        self, *, recovery_token: str, password: str, email: Optional[str] = None
    ) -> Dict[str, str]:
        """Set a new password with an operator-issued recovery token.

        ``POST /v1/auth/recover-password`` - public. Existing sessions of the
        account are invalidated. Returns ``{"status": "completed"}``.
        """

        return cast(
            Dict[str, str],
            self._client.request(
                "auth.recover_password",
                json=_setup_body(recovery_token, password, email, key="recovery_token"),
                cast_to=Dict[str, str],
            ),
        )

    def logout(self) -> None:
        """End every session of the signed-in user (``POST /v1/auth/logout``, bearer only).

        All access tokens of the user stop working immediately and refresh
        sessions are revoked. A client created with ``email=``/``password=``
        forgets its cached token, so its next call signs in again.
        """

        self._client.request("auth.logout", cast_to=None)
        if self._client.auth is not None:
            self._client.auth.invalidate()


class AsyncAuthentication(AsyncResource):
    """Async variant of :class:`Authentication`."""

    async def register(
        self, *, name: str, admin_email: str, idempotency_key: Optional[str] = None
    ) -> TenantRegistration:
        """Async variant of :meth:`Authentication.register`."""

        return cast(
            TenantRegistration,
            await self._client.request(
                "tenants.register",
                json=_register_body(name, admin_email),
                idempotency_key=idempotency_key or new_idempotency_key(),
                cast_to=TenantRegistration,
            ),
        )

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

    async def recover_password(
        self, *, recovery_token: str, password: str, email: Optional[str] = None
    ) -> Dict[str, str]:
        """Async variant of :meth:`Authentication.recover_password`."""

        return cast(
            Dict[str, str],
            await self._client.request(
                "auth.recover_password",
                json=_setup_body(recovery_token, password, email, key="recovery_token"),
                cast_to=Dict[str, str],
            ),
        )

    async def logout(self) -> None:
        """Async variant of :meth:`Authentication.logout`."""

        await self._client.request("auth.logout", cast_to=None)
        if self._client.auth is not None:
            self._client.auth.invalidate()
