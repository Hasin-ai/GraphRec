"""String constants for fields GraphRec returns as plain strings.

Members are ``str`` subclasses, so ``version.status == ModelStatus.ACTIVE``
works and they can be passed anywhere a string is accepted. Response models
keep plain ``str`` fields so a new server-side value never breaks parsing.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "ApiKeyStatus",
    "AvailabilityStatus",
    "EventType",
    "FallbackTier",
    "FeedbackType",
    "ModelStatus",
    "PlanCode",
    "RecommendationStrategy",
    "TenantStatus",
    "TrainingStatus",
    "UsageType",
    "UserRole",
]


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return str(self.value)


class EventType(_StrEnum):
    """Interaction types from the GraphRec specification (views, clicks, cart, purchases...)."""

    VIEW = "view"
    CLICK = "click"
    ADD_TO_CART = "add_to_cart"
    REMOVE_FROM_CART = "remove_from_cart"
    PURCHASE = "purchase"
    RATING = "rating"
    SEARCH = "search"
    ADD_TO_WISHLIST = "add_to_wishlist"


class FeedbackType(_StrEnum):
    IMPRESSION = "impression"
    CLICK = "click"
    CONVERSION = "conversion"


class AvailabilityStatus(_StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    OUT_OF_STOCK = "out_of_stock"
    DISCONTINUED = "discontinued"


class ModelStatus(_StrEnum):
    ELIGIBLE = "eligible"
    ACTIVE = "active"
    RETIRED = "retired"
    ARCHIVED = "archived"


class TrainingStatus(_StrEnum):
    QUEUED = "queued"
    PREPARING_DATA = "preparing_data"
    TRAINING = "training"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TenantStatus(_StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETING = "deleting"
    DELETED = "deleted"


class ApiKeyStatus(_StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class RecommendationStrategy(_StrEnum):
    PERSONALIZED = "personalized"
    POPULAR_FALLBACK = "popular_fallback"


class FallbackTier(_StrEnum):
    NONE = "none"
    TENANT_POPULAR = "tenant_popular"


class PlanCode(_StrEnum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"


class UsageType(_StrEnum):
    ACCEPTED_EVENTS = "accepted_events"
    RECOMMENDATION_REQUESTS = "recommendation_requests"
    TRAINING_JOBS = "training_jobs"
    TRAINING_CPU_SECONDS = "training_cpu_seconds"
    STORED_PRODUCTS = "stored_products"
    ARTIFACT_STORAGE_BYTES = "artifact_storage_bytes"
    ACTIVE_MODEL_VERSIONS = "active_model_versions"
    INFERENCE_REPLICAS = "inference_replicas"
    REPLICA_RUNTIME_MINUTES = "replica_runtime_minutes"


class UserRole(_StrEnum):
    TENANT_ADMINISTRATOR = "tenant_administrator"
    TENANT_DEVELOPER = "tenant_developer"
