"""SQLAlchemy models for the identity and tenancy tables.

The models mirror migration 0002 and do not create it. Alembic remains the only
thing that changes the schema, so `metadata.create_all` is never called — if the
two ever disagree, the migration is right and the model is the bug.
"""

from __future__ import annotations

from graphrec.db.models.base import Base, TenantOwned
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
from graphrec.db.models.subscription import (
    QuotaOverride,
    TenantResourceQuota,
    TenantSubscription,
)

__all__ = [
    "ApiKey",
    "Base",
    "Invitation",
    "PlatformUser",
    "PlatformUserPermission",
    "PricingPlan",
    "QuotaOverride",
    "RecoveryToken",
    "RefreshSession",
    "Tenant",
    "TenantOwned",
    "TenantResourceQuota",
    "TenantSubscription",
    "TenantUser",
]
