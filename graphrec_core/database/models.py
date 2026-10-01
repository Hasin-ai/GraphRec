from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RecommendationRecord(Base):
    __tablename__ = "recommendation_records"
    __table_args__ = (ForeignKeyConstraint(["tenant_id", "external_customer_id"],
        ["customers.tenant_id", "customers.external_id"], name="fk_recommendation_record_customer"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    external_customer_id: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationFeedback(Base):
    __tablename__ = "recommendation_feedback"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "request_id"], ["recommendation_records.tenant_id", "recommendation_records.request_id"]),
        ForeignKeyConstraint(["tenant_id", "recommendation_result_id"],
                             ["recommendation_results.tenant_id", "recommendation_results.id"],
                             name="fk_recommendation_feedback_result_tenant"),
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    recommendation_result_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    feedback_type: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationResult(Base):
    __tablename__ = "recommendation_results"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "request_id"],
                             ["recommendation_records.tenant_id", "recommendation_records.request_id"],
                             ondelete="CASCADE", name="fk_recommendation_result_request"),
        ForeignKeyConstraint(["tenant_id", "external_product_id"],
                             ["products.tenant_id", "products.external_id"],
                             name="fk_recommendation_result_product"),
        UniqueConstraint("tenant_id", "request_id", "rank_position", name="uq_recommendation_result_rank"),
        UniqueConstraint("tenant_id", "request_id", "external_product_id", name="uq_recommendation_result_product"),
        UniqueConstraint("tenant_id", "id", name="uq_recommendation_result_tenant_id"),
        CheckConstraint("rank_position >= 1", name="ck_recommendation_result_position"),
        Index("ix_recommendation_results_tenant_product", "tenant_id", "external_product_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    rank_position: Mapped[int] = mapped_column(nullable=False)
    model_score: Mapped[Decimal | None] = mapped_column(Numeric)
    final_order_score: Mapped[Decimal | None] = mapped_column(Numeric)
    candidate_source: Mapped[str] = mapped_column(String(48), nullable=False)
    strategy: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PricingPlan(Base):
    __tablename__ = "pricing_plans"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active','suspended','deleting','deleted')", name="ck_tenants_status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TenantUser(Base):
    __tablename__ = "tenant_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_tenant_users_tenant_email"),
        UniqueConstraint("tenant_id", "id", name="uq_tenant_users_tenant_id_id"),
        CheckConstraint(
            "role IN ('tenant_administrator','tenant_developer')",
            name="ck_tenant_users_role",
        ),
        CheckConstraint(
            "status IN ('invited','active','locked','disabled')",
            name="ck_tenant_users_status",
        ),
        Index("ix_tenant_users_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    credential_digest: Mapped[str | None] = mapped_column(Text)
    auth_epoch: Mapped[int] = mapped_column(nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantSubscription(Base):
    __tablename__ = "tenant_subscriptions"
    __table_args__ = (
        CheckConstraint("period_end > period_start", name="ck_subscription_period"),
        CheckConstraint("status IN ('active')", name="ck_subscription_status_current_slice"),
        UniqueConstraint("tenant_id", name="uq_tenant_current_subscription"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("pricing_plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    project_defaults: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TenantResourceQuota(Base):
    __tablename__ = "tenant_resource_quotas"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_tenant_time", "tenant_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_reference: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_reference: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    correlation_reference: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    redacted_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RegistrationRequest(Base):
    """Public idempotency record; not tenant-selectable and never stores the raw key."""

    __tablename__ = "registration_requests"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (Index("ix_security_events_severity_time", "severity", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sanitized_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_users.tenant_id", "tenant_users.id"],
            ondelete="CASCADE",
            name="fk_refresh_sessions_tenant_user",
        ),
        CheckConstraint("expires_at > created_at", name="ck_refresh_sessions_expiry"),
        Index("ix_refresh_sessions_tenant_user", "tenant_id", "user_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_from_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class AccountSetupToken(Base):
    """Single-use credential for activating an invited tenant user (stored as a hash)."""

    __tablename__ = "account_setup_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_users.tenant_id", "tenant_users.id"],
            ondelete="CASCADE",
            name="fk_account_setup_tokens_tenant_user",
        ),
        CheckConstraint("expires_at > created_at", name="ck_account_setup_tokens_expiry"),
        UniqueConstraint("token_hash", name="uq_account_setup_tokens_hash"),
        Index("ix_account_setup_tokens_tenant_user", "tenant_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountRecoveryToken(Base):
    """Single-use reset proof; only the SHA-256 digest is persisted."""

    __tablename__ = "account_recovery_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["tenant_users.tenant_id", "tenant_users.id"],
            ondelete="CASCADE", name="fk_account_recovery_tokens_user",
        ),
        CheckConstraint("expires_at > created_at", name="ck_account_recovery_tokens_expiry"),
        Index("ix_account_recovery_tokens_user", "tenant_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_usage_events_tenant_idempotency"
        ),
        CheckConstraint("quantity >= 0", name="ck_usage_events_quantity"),
        CheckConstraint(
            "usage_type IN ('accepted_events','recommendation_requests','training_jobs',"
            "'training_cpu_seconds','stored_products','artifact_storage_bytes',"
            "'active_model_versions','inference_replicas','replica_runtime_minutes')",
            name="ck_usage_events_type",
        ),
        Index("ix_usage_events_tenant_occurred", "tenant_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    usage_type: Mapped[str] = mapped_column(String(48), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_api_keys_tenant_name"),
        UniqueConstraint("key_hash", name="uq_api_keys_current_hash"),
        CheckConstraint("hash_version > 0", name="ck_api_keys_hash_version"),
        CheckConstraint(
            "grace_expires_at IS NULL OR previous_key_hash IS NOT NULL",
            name="ck_api_keys_grace_predecessor",
        ),
        Index("ix_api_keys_tenant_created", "tenant_id", "created_at"),
        Index("ix_api_keys_prefix", "key_prefix"),
        Index("ix_api_keys_previous_hash", "previous_key_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash_version: Mapped[int] = mapped_column(nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_key_prefix: Mapped[str | None] = mapped_column(String(16))
    previous_key_hash: Mapped[str | None] = mapped_column(String(64))
    previous_hash_version: Mapped[int | None] = mapped_column()
    grace_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_products_tenant_external"),
        Index("ix_products_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    category: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    availability_status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id", name="uq_customers_tenant_external"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CustomerEvent(Base):
    __tablename__ = "customer_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", name="uq_customer_events_tenant_event"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["customers.tenant_id", "customers.external_id"],
                             name="fk_customer_event_customer"),
        Index("ix_customer_events_tenant_time", "tenant_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    user_id: Mapped[str | None] = mapped_column(Text)
    external_product_id: Mapped[str | None] = mapped_column(String(100))
    context_json: Mapped[dict[str, Any]] = mapped_column("context", JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventBatch(Base):
    __tablename__ = "event_batches"
    __table_args__ = (
        Index("ix_event_batches_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    request_id: Mapped[str | None] = mapped_column(String(128))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    outcomes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    accepted_count: Mapped[int] = mapped_column(nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogSync(Base):
    __tablename__ = "catalog_syncs"
    __table_args__ = (Index("ix_catalog_syncs_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted_count: Mapped[int] = mapped_column(nullable=False)
    created_count: Mapped[int] = mapped_column(nullable=False)
    updated_count: Mapped[int] = mapped_column(nullable=False)
    skipped_count: Mapped[int] = mapped_column(nullable=False)
    rejected_count: Mapped[int] = mapped_column(nullable=False)
    outcomes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version_tag", name="uq_model_versions_tenant_tag"),
        Index("ix_model_versions_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    version_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    model_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="eligible")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelDeployment(Base):
    __tablename__ = "model_deployments"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "desired_model_version_id"],
                             ["model_versions.tenant_id", "model_versions.id"], name="fk_deployment_desired"),
        ForeignKeyConstraint(["tenant_id", "active_model_version_id"],
                             ["model_versions.tenant_id", "model_versions.id"], name="fk_deployment_active"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False)
    desired_model_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    active_model_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    desired_capacity: Mapped[int] = mapped_column(nullable=False, default=1)
    ready_capacity: Mapped[int] = mapped_column(nullable=False, default=0)
    last_transition_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)


class TrainingJob(Base):
    __tablename__ = "training_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_id", name="uq_training_jobs_tenant_request"),
        Index("ix_training_jobs_tenant_created", "tenant_id", "created_at"),
    )

    progress: Mapped[int] = mapped_column(default=0)
    stage: Mapped[str] = mapped_column(String(40), default="completed")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(default=0)
    request_id: Mapped[str | None] = mapped_column(String(128))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    model_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="succeeded")
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dataset_snapshot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    model_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DatasetSnapshot(Base):
    __tablename__ = "dataset_snapshots"
    __table_args__ = (
        Index("ix_dataset_snapshots_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    training_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_count: Mapped[int] = mapped_column(nullable=False, default=0)
    product_count: Mapped[int] = mapped_column(nullable=False, default=0)
    user_count: Mapped[int] = mapped_column(nullable=False, default=0)
    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DatasetSnapshotContent(Base):
    __tablename__ = "dataset_snapshot_contents"

    snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("dataset_snapshots.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ServingRequest(Base):
    """One row per recommendation request served, the source for /v1/metrics/summary.

    Append-only: the API measures rates and latency percentiles over a window of
    these rows rather than reporting nominal values.
    """

    __tablename__ = "serving_requests"
    __table_args__ = (
        CheckConstraint("outcome IN ('served','error')", name="ck_serving_requests_outcome"),
        CheckConstraint("latency_ms >= 0", name="ck_serving_requests_latency"),
        Index("ix_serving_requests_tenant_occurred", "tenant_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    model_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False)
    item_count: Mapped[int] = mapped_column(nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
