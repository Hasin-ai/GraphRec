"""Typed request and response models."""

from ._base import GraphRecModel, InputModel, ItemList
from .api_keys import ApiKey, ApiKeyList, ApiKeyWithSecret
from .auth import AuthTokenPair, TenantRegistration
from .billing import Subscription, UsageDimension, UsageSummary
from .catalog import (
    BulkUpsertFailure,
    Product,
    ProductBulkUpsertResult,
    ProductInput,
    ProductList,
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
)
from .recommendations import FeedbackReceipt, RecommendationItem, Recommendations
from .serving import (
    AutoscalingStatus,
    DeploymentStatus,
    MetricsSummary,
    QualitySummary,
    Replica,
    ReplicaStatus,
)

__all__ = [
    "ApiKey",
    "ApiKeyList",
    "ApiKeyWithSecret",
    "AuditRecord",
    "AuditRecordList",
    "AuthTokenPair",
    "AutoscalingStatus",
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
    "QualitySummary",
    "QuotaOverride",
    "RecommendationItem",
    "Recommendations",
    "Replica",
    "ReplicaStatus",
    "Subscription",
    "TenantRegistration",
    "TrainingJob",
    "TrainingJobList",
    "UsageDimension",
    "UsageSummary",
]
