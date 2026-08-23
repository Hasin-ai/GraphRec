"""SQLAlchemy models for the identity and tenancy tables.

The models mirror migration 0002 and do not create it. Alembic remains the only
thing that changes the schema, so `metadata.create_all` is never called — if the
two ever disagree, the migration is right and the model is the bug.
"""

from __future__ import annotations

from graphrec.db.models.base import Base, TenantOwned
from graphrec.db.models.catalog import Product, ProductCategory
from graphrec.db.models.credentials import ApiKey
from graphrec.db.models.identity import (
    Invitation,
    PlatformUser,
    PlatformUserPermission,
    PricingPlan,
    RecoveryToken,
    RefreshSession,
    Tenant,
    TenantUser,
)
from graphrec.db.models.ingestion import (
    Customer,
    IngestStagingItem,
    InteractionEvent,
    Submission,
    SubmissionError,
)
from graphrec.db.models.jobs import Job
from graphrec.db.models.metering import MonthlyUsageAggregate, UsageEvent
from graphrec.db.models.registry import ModelEvaluationMetric, ModelVersion
from graphrec.db.models.subscription import (
    QuotaOverride,
    TenantResourceQuota,
    TenantSubscription,
)
from graphrec.db.models.training import (
    DatasetSnapshot,
    Model,
    TrainingJob,
    TrainingMetric,
)

__all__ = [
    "ApiKey",
    "Base",
    "Customer",
    "DatasetSnapshot",
    "IngestStagingItem",
    "InteractionEvent",
    "Invitation",
    "Job",
    "Model",
    "ModelEvaluationMetric",
    "ModelVersion",
    "MonthlyUsageAggregate",
    "PlatformUser",
    "PlatformUserPermission",
    "PricingPlan",
    "Product",
    "ProductCategory",
    "QuotaOverride",
    "RecoveryToken",
    "RefreshSession",
    "Submission",
    "SubmissionError",
    "Tenant",
    "TenantOwned",
    "TenantResourceQuota",
    "TenantSubscription",
    "TenantUser",
    "TrainingJob",
    "TrainingMetric",
    "UsageEvent",
]
