from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Type, cast

import httpx

from ._auth import ApiKeyAuth, Auth, BearerTokenAuth, PasswordAuth
from ._base_client import AsyncAPIClient, SyncAPIClient, TimeoutTypes
from ._constants import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_BATCH_ITEMS,
    DEFAULT_MAX_BODY_BYTES,
    DEFAULT_MAX_RETRIES,
    ENV_ACCESS_TOKEN,
    ENV_API_KEY,
    ENV_BASE_URL,
)
from ._namespaces import (
    AsyncPlatformNamespace,
    AsyncStorefrontNamespace,
    AsyncTenantNamespace,
    PlatformNamespace,
    StorefrontNamespace,
    TenantNamespace,
)
from ._retry import RetryPolicy
from .errors import ConfigurationError

__all__ = ["AsyncGraphRec", "GraphRec"]


def _resolve_auth(
    *,
    auth: Optional[Auth],
    api_key: Optional[str],
    access_token: Optional[str],
    email: Optional[str],
    password: Optional[str],
    use_env: bool,
) -> Optional[Auth]:
    given = [
        name
        for name, value in (
            ("auth", auth),
            ("api_key", api_key),
            ("access_token", access_token),
            ("email/password", email or password),
        )
        if value
    ]
    if len(given) > 1:
        raise ConfigurationError(f"Pass only one credential, got: {', '.join(given)}")
    if auth is not None:
        return auth
    if api_key:
        return ApiKeyAuth(api_key)
    if access_token:
        return BearerTokenAuth(access_token)
    if email or password:
        if not (email and password):
            raise ConfigurationError("email and password must be passed together")
        return PasswordAuth(email, password)
    if use_env:
        env_key = os.environ.get(ENV_API_KEY)
        if env_key:
            return ApiKeyAuth(env_key)
        env_token = os.environ.get(ENV_ACCESS_TOKEN)
        if env_token:
            return BearerTokenAuth(env_token)
    return None


def _retry_policy(max_retries: int, retry_policy: Optional[RetryPolicy]) -> RetryPolicy:
    if retry_policy is not None:
        return retry_policy
    return RetryPolicy(max_retries=max_retries)


class _ClientOptions:
    """Constructor arguments kept so ``with_credentials`` can clone a client."""

    def __init__(self, **values: Any) -> None:
        self.values: Dict[str, Any] = values


class GraphRec:
    """Synchronous GraphRec client.

    Resources are grouped by audience: ``client.storefront`` (events,
    recommendations, feedback), ``client.tenant`` (tenant administration) and
    ``client.platform`` (cross-tenant operations).

    Storefront backend (API key)::

        from graphrec_sdk import GraphRec

        client = GraphRec(base_url="https://graphrec.example.com", api_key="gr_live_...")
        recs = client.storefront.recommendations.get(user_id="customer-42", top_n=8)

    Tenant administration (auto-login, token renewed before expiry)::

        admin = GraphRec(email="admin@shop.example", password="...")
        key = admin.tenant.api_keys.create(name="storefront", scopes=STOREFRONT_KEY_SCOPES)

    Platform operations (``PLATFORM_ADMIN_TOKEN``)::

        ops = GraphRec(access_token=os.environ["PLATFORM_ADMIN_TOKEN"])
        for t in ops.platform.tenants.list():
            print(t.slug, t.status)

    Credentials fall back to ``GRAPHREC_API_KEY`` / ``GRAPHREC_ACCESS_TOKEN`` and the
    URL to ``GRAPHREC_BASE_URL`` (default ``http://localhost:8010``).
    """

    storefront: StorefrontNamespace
    tenant: TenantNamespace
    platform: PlatformNamespace

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        auth: Optional[Auth] = None,
        timeout: TimeoutTypes = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_policy: Optional[RetryPolicy] = None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        max_batch_items: int = DEFAULT_MAX_BATCH_ITEMS,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
        use_env: bool = True,
    ) -> None:
        resolved_url = (
            base_url or (os.environ.get(ENV_BASE_URL) if use_env else None) or DEFAULT_BASE_URL
        )
        self._options = _ClientOptions(
            base_url=resolved_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_policy=retry_policy,
            max_body_bytes=max_body_bytes,
            max_batch_items=max_batch_items,
            default_headers=default_headers,
        )
        self._api = SyncAPIClient(
            base_url=resolved_url,
            auth=_resolve_auth(
                auth=auth,
                api_key=api_key,
                access_token=access_token,
                email=email,
                password=password,
                use_env=use_env,
            ),
            timeout=timeout,
            retry=_retry_policy(max_retries, retry_policy),
            max_body_bytes=max_body_bytes,
            max_batch_items=max_batch_items,
            default_headers=default_headers,
            http_client=http_client,
        )
        self.storefront = StorefrontNamespace(self._api)
        self.tenant = TenantNamespace(self._api)
        self.platform = PlatformNamespace(self._api)

    @property
    def base_url(self) -> str:
        return self._api.base_url

    @property
    def credentials(self) -> Optional[Auth]:
        """The active credential strategy (``ApiKeyAuth``, ``PasswordAuth``...)."""

        return self._api.auth

    def health(self) -> Dict[str, Any]:
        """``GET /healthz`` - database connectivity check, no credentials needed."""

        return cast(Dict[str, Any], self._api.request("health.check", cast_to=Dict[str, Any]))

    def with_credentials(
        self,
        *,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        auth: Optional[Auth] = None,
    ) -> GraphRec:
        """A client for the same server with different credentials, sharing the connection pool.

        Close the original client last - the copy never closes the shared pool.
        """

        return type(self)(
            **self._options.values,
            api_key=api_key,
            access_token=access_token,
            email=email,
            password=password,
            auth=auth,
            http_client=self._api._http,
            use_env=False,
        )

    def close(self) -> None:
        self._api.close()

    def __enter__(self) -> GraphRec:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"GraphRec(base_url={self.base_url!r}, credentials={self.credentials!r})"


class AsyncGraphRec:
    """Asynchronous GraphRec client with the same resources as :class:`GraphRec`.

    ::

        async with AsyncGraphRec(api_key="gr_live_...") as client:
            recs = await client.storefront.recommendations.get(user_id="customer-42")
    """

    storefront: AsyncStorefrontNamespace
    tenant: AsyncTenantNamespace
    platform: AsyncPlatformNamespace

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        auth: Optional[Auth] = None,
        timeout: TimeoutTypes = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_policy: Optional[RetryPolicy] = None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        max_batch_items: int = DEFAULT_MAX_BATCH_ITEMS,
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        use_env: bool = True,
    ) -> None:
        resolved_url = (
            base_url or (os.environ.get(ENV_BASE_URL) if use_env else None) or DEFAULT_BASE_URL
        )
        self._options = _ClientOptions(
            base_url=resolved_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_policy=retry_policy,
            max_body_bytes=max_body_bytes,
            max_batch_items=max_batch_items,
            default_headers=default_headers,
        )
        self._api = AsyncAPIClient(
            base_url=resolved_url,
            auth=_resolve_auth(
                auth=auth,
                api_key=api_key,
                access_token=access_token,
                email=email,
                password=password,
                use_env=use_env,
            ),
            timeout=timeout,
            retry=_retry_policy(max_retries, retry_policy),
            max_body_bytes=max_body_bytes,
            max_batch_items=max_batch_items,
            default_headers=default_headers,
            http_client=http_client,
        )
        self.storefront = AsyncStorefrontNamespace(self._api)
        self.tenant = AsyncTenantNamespace(self._api)
        self.platform = AsyncPlatformNamespace(self._api)

    @property
    def base_url(self) -> str:
        return self._api.base_url

    @property
    def credentials(self) -> Optional[Auth]:
        return self._api.auth

    async def health(self) -> Dict[str, Any]:
        """Async variant of :meth:`GraphRec.health`."""

        return cast(Dict[str, Any], await self._api.request("health.check", cast_to=Dict[str, Any]))

    def with_credentials(
        self,
        *,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        auth: Optional[Auth] = None,
    ) -> AsyncGraphRec:
        """Async variant of :meth:`GraphRec.with_credentials`."""

        cls: Type[AsyncGraphRec] = type(self)
        return cls(
            **self._options.values,
            api_key=api_key,
            access_token=access_token,
            email=email,
            password=password,
            auth=auth,
            http_client=self._api._http,
            use_env=False,
        )

    async def close(self) -> None:
        await self._api.close()

    async def __aenter__(self) -> AsyncGraphRec:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"AsyncGraphRec(base_url={self.base_url!r}, credentials={self.credentials!r})"
