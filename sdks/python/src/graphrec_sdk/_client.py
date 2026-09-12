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
from ._retry import RetryPolicy
from .errors import ConfigurationError
from .resources import (
    ApiKeys,
    AsyncApiKeys,
    AsyncAuthentication,
    AsyncDatasets,
    AsyncDeployment,
    AsyncEvents,
    AsyncFeedback,
    AsyncMetrics,
    AsyncModelVersions,
    AsyncPlatform,
    AsyncProducts,
    AsyncRecommendationsResource,
    AsyncSubscriptions,
    AsyncTenants,
    AsyncTrainingJobs,
    AsyncUsage,
    Authentication,
    Datasets,
    Deployment,
    Events,
    Feedback,
    Metrics,
    ModelVersions,
    Platform,
    Products,
    RecommendationsResource,
    Subscriptions,
    Tenants,
    TrainingJobs,
    Usage,
)

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

    Storefront backend (API key)::

        from graphrec_sdk import GraphRec

        client = GraphRec(base_url="https://graphrec.example.com", api_key="gr_live_...")
        recs = client.recommendations.get(user_id="customer-42", top_n=8)

    Tenant administration (auto-login, token renewed before expiry)::

        admin = GraphRec(email="admin@shop.example", password="...")
        key = admin.api_keys.create(name="storefront", scopes=STOREFRONT_KEY_SCOPES)

    Credentials fall back to ``GRAPHREC_API_KEY`` / ``GRAPHREC_ACCESS_TOKEN`` and the
    URL to ``GRAPHREC_BASE_URL`` (default ``http://localhost:8010``).
    """

    tenants: Tenants
    auth: Authentication
    api_keys: ApiKeys
    subscription: Subscriptions
    usage: Usage
    products: Products
    events: Events
    datasets: Datasets
    model_versions: ModelVersions
    training_jobs: TrainingJobs
    deployment: Deployment
    metrics: Metrics
    recommendations: RecommendationsResource
    feedback: Feedback
    platform: Platform

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
        self.tenants = Tenants(self._api)
        self.auth = Authentication(self._api)
        self.api_keys = ApiKeys(self._api)
        self.subscription = Subscriptions(self._api)
        self.usage = Usage(self._api)
        self.products = Products(self._api)
        self.events = Events(self._api)
        self.datasets = Datasets(self._api)
        self.model_versions = ModelVersions(self._api)
        self.training_jobs = TrainingJobs(self._api)
        self.deployment = Deployment(self._api)
        self.metrics = Metrics(self._api)
        self.recommendations = RecommendationsResource(self._api)
        self.feedback = Feedback(self._api)
        self.platform = Platform(self._api)

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
            recs = await client.recommendations.get(user_id="customer-42")
    """

    tenants: AsyncTenants
    auth: AsyncAuthentication
    api_keys: AsyncApiKeys
    subscription: AsyncSubscriptions
    usage: AsyncUsage
    products: AsyncProducts
    events: AsyncEvents
    datasets: AsyncDatasets
    model_versions: AsyncModelVersions
    training_jobs: AsyncTrainingJobs
    deployment: AsyncDeployment
    metrics: AsyncMetrics
    recommendations: AsyncRecommendationsResource
    feedback: AsyncFeedback
    platform: AsyncPlatform

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
        self.tenants = AsyncTenants(self._api)
        self.auth = AsyncAuthentication(self._api)
        self.api_keys = AsyncApiKeys(self._api)
        self.subscription = AsyncSubscriptions(self._api)
        self.usage = AsyncUsage(self._api)
        self.products = AsyncProducts(self._api)
        self.events = AsyncEvents(self._api)
        self.datasets = AsyncDatasets(self._api)
        self.model_versions = AsyncModelVersions(self._api)
        self.training_jobs = AsyncTrainingJobs(self._api)
        self.deployment = AsyncDeployment(self._api)
        self.metrics = AsyncMetrics(self._api)
        self.recommendations = AsyncRecommendationsResource(self._api)
        self.feedback = AsyncFeedback(self._api)
        self.platform = AsyncPlatform(self._api)

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
