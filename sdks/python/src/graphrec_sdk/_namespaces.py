"""Audience namespaces: ``client.storefront``, ``client.tenant`` and ``client.platform``.

Each namespace groups the resources one kind of caller uses, which also maps to
the credential it needs:

* ``storefront`` - the shop's site/app backend with a storefront API key
  (events, recommendations, feedback).
* ``tenant`` - tenant administrators and developers, usually signed in with
  email/password (catalog, users, API keys, datasets, models, training,
  policies, serving status, billing).
* ``platform`` - the platform operator with ``PLATFORM_ADMIN_TOKEN``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .resources.api_keys import ApiKeys, AsyncApiKeys
from .resources.billing import AsyncSubscriptions, AsyncUsage, Subscriptions, Usage
from .resources.datasets import AsyncDatasets, Datasets
from .resources.events import AsyncEvents, Events
from .resources.ml import AsyncModelVersions, AsyncTrainingJobs, ModelVersions, TrainingJobs
from .resources.platform import (
    AsyncPlatformOperations,
    AsyncPlatformPlans,
    AsyncPlatformTenants,
    PlatformOperations,
    PlatformPlans,
    PlatformTenants,
)
from .resources.policies import (
    AsyncRecommendationPolicyResource,
    AsyncRetrainingPolicyResource,
    RecommendationPolicyResource,
    RetrainingPolicyResource,
)
from .resources.products import AsyncProducts, Products
from .resources.recommendations import (
    AsyncFeedback,
    AsyncRecommendationsResource,
    Feedback,
    RecommendationsResource,
)
from .resources.serving import AsyncDeployment, AsyncMetrics, Deployment, Metrics
from .resources.tenant_users import AsyncTenantUsers, TenantUsers
from .resources.account import Account, AsyncAccount, AsyncTenantAudit, TenantAudit
from .resources.operators import AsyncPlatformOperators, PlatformOperators
from .resources.tenants import AsyncAuthentication, Authentication

if TYPE_CHECKING:
    from ._base_client import AsyncAPIClient, SyncAPIClient

__all__ = [
    "AsyncPlatformNamespace",
    "AsyncStorefrontNamespace",
    "AsyncTenantNamespace",
    "PlatformNamespace",
    "StorefrontNamespace",
    "TenantNamespace",
]


class StorefrontNamespace:
    """Calls a shop's site or backend makes with a storefront API key."""

    events: Events
    recommendations: RecommendationsResource
    feedback: Feedback

    def __init__(self, api: SyncAPIClient) -> None:
        self.events = Events(api)
        self.recommendations = RecommendationsResource(api)
        self.feedback = Feedback(api)


class AsyncStorefrontNamespace:
    """Async variant of :class:`StorefrontNamespace`."""

    events: AsyncEvents
    recommendations: AsyncRecommendationsResource
    feedback: AsyncFeedback

    def __init__(self, api: AsyncAPIClient) -> None:
        self.events = AsyncEvents(api)
        self.recommendations = AsyncRecommendationsResource(api)
        self.feedback = AsyncFeedback(api)


class TenantNamespace:
    """Tenant-scoped administration (one tenant, chosen by the credential)."""

    auth: Authentication
    users: TenantUsers
    api_keys: ApiKeys
    subscription: Subscriptions
    usage: Usage
    catalog: Products
    datasets: Datasets
    model_versions: ModelVersions
    training_jobs: TrainingJobs
    retraining_policy: RetrainingPolicyResource
    recommendation_policy: RecommendationPolicyResource
    deployment: Deployment
    metrics: Metrics
    account: Account
    audit: TenantAudit

    def __init__(self, api: SyncAPIClient) -> None:
        self.account = Account(api)
        self.audit = TenantAudit(api)
        self.auth = Authentication(api)
        self.users = TenantUsers(api)
        self.api_keys = ApiKeys(api)
        self.subscription = Subscriptions(api)
        self.usage = Usage(api)
        self.catalog = Products(api)
        self.datasets = Datasets(api)
        self.model_versions = ModelVersions(api)
        self.training_jobs = TrainingJobs(api)
        self.retraining_policy = RetrainingPolicyResource(api)
        self.recommendation_policy = RecommendationPolicyResource(api)
        self.deployment = Deployment(api)
        self.metrics = Metrics(api)


class AsyncTenantNamespace:
    """Async variant of :class:`TenantNamespace`."""

    auth: AsyncAuthentication
    users: AsyncTenantUsers
    api_keys: AsyncApiKeys
    subscription: AsyncSubscriptions
    usage: AsyncUsage
    catalog: AsyncProducts
    datasets: AsyncDatasets
    model_versions: AsyncModelVersions
    training_jobs: AsyncTrainingJobs
    retraining_policy: AsyncRetrainingPolicyResource
    recommendation_policy: AsyncRecommendationPolicyResource
    deployment: AsyncDeployment
    metrics: AsyncMetrics
    account: AsyncAccount
    audit: AsyncTenantAudit

    def __init__(self, api: AsyncAPIClient) -> None:
        self.account = AsyncAccount(api)
        self.audit = AsyncTenantAudit(api)
        self.auth = AsyncAuthentication(api)
        self.users = AsyncTenantUsers(api)
        self.api_keys = AsyncApiKeys(api)
        self.subscription = AsyncSubscriptions(api)
        self.usage = AsyncUsage(api)
        self.catalog = AsyncProducts(api)
        self.datasets = AsyncDatasets(api)
        self.model_versions = AsyncModelVersions(api)
        self.training_jobs = AsyncTrainingJobs(api)
        self.retraining_policy = AsyncRetrainingPolicyResource(api)
        self.recommendation_policy = AsyncRecommendationPolicyResource(api)
        self.deployment = AsyncDeployment(api)
        self.metrics = AsyncMetrics(api)


class PlatformNamespace(PlatformOperations):
    """Cross-tenant operations: ``tenants``, ``plans`` plus ``status()``,
    ``list_failures()`` and ``list_audit_logs()``."""

    tenants: PlatformTenants
    plans: PlatformPlans
    operators: PlatformOperators

    def __init__(self, api: SyncAPIClient) -> None:
        super().__init__(api)
        self.tenants = PlatformTenants(api)
        self.plans = PlatformPlans(api)
        self.operators = PlatformOperators(api)


class AsyncPlatformNamespace(AsyncPlatformOperations):
    """Async variant of :class:`PlatformNamespace`."""

    tenants: AsyncPlatformTenants
    plans: AsyncPlatformPlans
    operators: AsyncPlatformOperators

    def __init__(self, api: AsyncAPIClient) -> None:
        super().__init__(api)
        self.tenants = AsyncPlatformTenants(api)
        self.plans = AsyncPlatformPlans(api)
        self.operators = AsyncPlatformOperators(api)
