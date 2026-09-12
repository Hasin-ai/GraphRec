"""Credential strategies.

GraphRec accepts two ``Authorization`` schemes:

* ``ApiKey gr_live_…`` - long-lived, scoped server credentials created under
  *Integration → API keys*. Use these from your storefront backend.
* ``Bearer <jwt>`` - short-lived (15 min by default) access tokens issued by
  ``POST /v1/auth/login`` for tenant users. Required for API-key management.

The API has no refresh endpoint, so :class:`PasswordAuth` transparently logs in
again shortly before the access token expires or when the server answers
``token_expired``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, Optional

from ._constants import TOKEN_EXPIRY_SKEW_SECONDS

if TYPE_CHECKING:
    from .models.auth import AuthTokenPair

__all__ = ["ApiKeyAuth", "Auth", "BearerTokenAuth", "PasswordAuth"]

SyncLogin = Callable[[str, str], "AuthTokenPair"]
AsyncLogin = Callable[[str, str], Awaitable["AuthTokenPair"]]


class Auth:
    """Base credential strategy."""

    #: ``"api_key"`` or ``"bearer"``.
    credential_type: str = ""

    def headers(self, login: SyncLogin) -> Dict[str, str]:
        raise NotImplementedError

    async def async_headers(self, login: AsyncLogin) -> Dict[str, str]:
        return self.headers(_no_sync_login)

    @property
    def can_refresh(self) -> bool:
        """Whether :meth:`invalidate` followed by a retry can recover from ``token_expired``."""

        return False

    def invalidate(self) -> None:
        """Forget any cached token so the next request obtains a new one."""


def _no_sync_login(email: str, password: str) -> AuthTokenPair:  # pragma: no cover
    raise RuntimeError("login is not available for this credential type")


class ApiKeyAuth(Auth):
    """``Authorization: ApiKey <secret>``."""

    credential_type = "api_key"

    def __init__(self, api_key: str) -> None:
        secret = (api_key or "").strip()
        if not secret:
            raise ValueError("api_key must be a non-empty string")
        self._secret = secret

    @property
    def prefix(self) -> str:
        """The non-secret prefix shown in the GraphRec console (``gr_live_xxxxxxxx``)."""

        return self._secret[:16]

    def headers(self, login: SyncLogin) -> Dict[str, str]:
        return {"Authorization": f"ApiKey {self._secret}"}

    def __repr__(self) -> str:
        return f"ApiKeyAuth(prefix={self.prefix!r})"


class BearerTokenAuth(Auth):
    """``Authorization: Bearer <access token>`` with a token you manage yourself."""

    credential_type = "bearer"

    def __init__(self, access_token: str) -> None:
        token = (access_token or "").strip()
        if not token:
            raise ValueError("access_token must be a non-empty string")
        self._token = token

    def headers(self, login: SyncLogin) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def __repr__(self) -> str:
        return "BearerTokenAuth(access_token=***)"


class PasswordAuth(Auth):
    """Log in with a tenant user's email and password and keep the token fresh."""

    credential_type = "bearer"

    def __init__(
        self,
        email: str,
        password: str,
        *,
        expiry_skew_seconds: float = TOKEN_EXPIRY_SKEW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not email or not password:
            raise ValueError("email and password are required")
        self.email = email
        self._password = password
        self._skew = expiry_skew_seconds
        self._clock = clock
        self._tokens: Optional[AuthTokenPair] = None
        self._expires_at = 0.0
        self._thread_lock = threading.Lock()
        self._async_lock: Optional[asyncio.Lock] = None

    @property
    def tokens(self) -> Optional[AuthTokenPair]:
        """The most recent token pair, or ``None`` before the first request."""

        return self._tokens

    @property
    def can_refresh(self) -> bool:
        return True

    def invalidate(self) -> None:
        self._expires_at = 0.0

    def _fresh(self) -> bool:
        return self._tokens is not None and self._clock() < self._expires_at

    def _store(self, tokens: AuthTokenPair) -> Dict[str, str]:
        self._tokens = tokens
        lifetime = max(float(tokens.expires_in) - self._skew, 0.0)
        self._expires_at = self._clock() + lifetime
        return {"Authorization": f"Bearer {tokens.access_token}"}

    def headers(self, login: SyncLogin) -> Dict[str, str]:
        with self._thread_lock:
            if self._fresh():
                assert self._tokens is not None
                return {"Authorization": f"Bearer {self._tokens.access_token}"}
            return self._store(login(self.email, self._password))

    async def async_headers(self, login: AsyncLogin) -> Dict[str, str]:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        async with self._async_lock:
            if self._fresh():
                assert self._tokens is not None
                return {"Authorization": f"Bearer {self._tokens.access_token}"}
            return self._store(await login(self.email, self._password))

    def __repr__(self) -> str:
        return f"PasswordAuth(email={self.email!r})"
