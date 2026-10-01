"""Typed request and response models."""

from ._base import GraphRecModel, InputModel, ItemList
from .api_keys import ApiKey, ApiKeyList, ApiKeyWithSecret
from .tenant_users import TenantUser, TenantUserInvitation, TenantUserList
from .auth import AuthTokenPair, TenantRegistration
from .billing import Subscription, UsageDimension, UsageSummary
from .catalog import (
    BulkUpsertFailure,
    Product,
    ProductBulkUpsertResult,
    ProductInput,
    ProductList,
    CatalogSync,
)
from .datasets import DatasetSnapshot, DatasetSnapshotList, DatasetUploadResult
from .events import EventBatch, EventBatchList, EventBatchResult, EventInput, EventReceipt
from .ml import ModelVersion, ModelVersionList, TrainingJob, TrainingJobList
from .platform import (
    AuditRecord,
    AuditRecordList,
    PlatformFailure,
    PlatformFailureList,
    PlatformTenant,
    PlatformTenantList,
    PricingPlan,
    PricingPlanList,
    QuotaOverride,
    TenantQuota,
)
from .recommendations import FeedbackReceipt, RecommendationItem, Recommendations
from .serving import (
    DeploymentStatus,
    MetricsSummary,
    QualitySummary,
)

__all__ = [
    "TenantUser",
    "TenantUserInvitation",
    "TenantUserList",
    "ApiKey",
    "ApiKeyList",
    "ApiKeyWithSecret",
    "AuditRecord",
    "AuditRecordList",
    "AuthTokenPair",
    "BulkUpsertFailure",
    "DatasetSnapshot",
    "DatasetSnapshotList",
    "DatasetUploadResult",
    "DeploymentStatus",
    "EventBatch",
    "EventBatchList",
    "EventBatchResult",
    "EventInput",
    "EventReceipt",
    "FeedbackReceipt",
    "GraphRecModel",
    "InputModel",
    "ItemList",
    "MetricsSummary",
    "ModelVersion",
    "ModelVersionList",
    "PlatformFailure",
    "PlatformFailureList",
    "PlatformTenant",
    "PlatformTenantList",
    "PricingPlan",
    "PricingPlanList",
    "Product",
    "ProductBulkUpsertResult",
    "ProductInput",
    "ProductList",
    "CatalogSync",
    "QualitySummary",
    "QuotaOverride",
    "TenantQuota",
    "RecommendationItem",
    "Recommendations",
    "Subscription",
    "TenantRegistration",
    "TrainingJob",
    "TrainingJobList",
    "UsageDimension",
    "UsageSummary",
]
