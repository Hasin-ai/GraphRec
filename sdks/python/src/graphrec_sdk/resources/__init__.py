"""Resource classes. Reach them through the audience namespaces on the client
(``client.storefront``, ``client.tenant``, ``client.platform``)."""

from .account import Account, AsyncAccount, AsyncTenantAudit, TenantAudit
from .api_keys import ApiKeys, AsyncApiKeys
from .billing import AsyncSubscriptions, AsyncUsage, Subscriptions, Usage
from .datasets import AsyncDatasets, Datasets
from .events import AsyncEvents, Events
from .ml import AsyncModelVersions, AsyncTrainingJobs, ModelVersions, TrainingJobs
from .platform import (
    AsyncPlatformOperations,
    AsyncPlatformPlanRequests,
    AsyncPlatformPlans,
    AsyncPlatformTenants,
    PlatformOperations,
    PlatformPlanRequests,
    PlatformPlans,
    PlatformTenants,
)
from .operators import AsyncPlatformOperators, PlatformOperators
from .policies import (
    AsyncRecommendationPolicyResource,
    AsyncRetrainingPolicyResource,
    RecommendationPolicyResource,
    RetrainingPolicyResource,
)
from .products import AsyncProducts, Products
from .recommendations import (
    AsyncFeedback,
    AsyncRecommendationsResource,
    Feedback,
    RecommendationsResource,
)
from .serving import AsyncDeployment, AsyncMetrics, Deployment, Metrics
from .tenant_users import AsyncTenantUsers, TenantUsers
from .tenants import AsyncAuthentication, Authentication

__all__ = [
    "Account",
    "AsyncAccount",
    "AsyncTenantAudit",
    "TenantAudit",
    "AsyncPlatformOperators",
    "PlatformOperators",
    "ApiKeys",
    "AsyncApiKeys",
    "AsyncAuthentication",
    "AsyncDatasets",
    "AsyncDeployment",
    "AsyncEvents",
    "AsyncFeedback",
    "AsyncMetrics",
    "AsyncModelVersions",
    "AsyncPlatformOperations",
    "AsyncPlatformPlanRequests",
    "AsyncPlatformPlans",
    "AsyncPlatformTenants",
    "AsyncProducts",
    "AsyncRecommendationPolicyResource",
    "AsyncRecommendationsResource",
    "AsyncRetrainingPolicyResource",
    "AsyncSubscriptions",
    "AsyncTenantUsers",
    "AsyncTrainingJobs",
    "AsyncUsage",
    "Authentication",
    "Datasets",
    "Deployment",
    "Events",
    "Feedback",
    "Metrics",
    "ModelVersions",
    "PlatformOperations",
    "PlatformPlanRequests",
    "PlatformPlans",
    "PlatformTenants",
    "Products",
    "RecommendationPolicyResource",
    "RecommendationsResource",
    "RetrainingPolicyResource",
    "Subscriptions",
    "TenantUsers",
    "TrainingJobs",
    "Usage",
]
