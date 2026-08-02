"""registration vertical slice

Revision ID: 0001_registration_slice
Revises:
Create Date: 2026-08-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_registration_slice"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FREE_PLAN_ID = "00000000-0000-4000-8000-000000000001"
FREE_LIMITS = {
    "accepted_events": 50000,
    "recommendation_requests": 20000,
    "requests_per_minute": 60,
    "concurrent_recommendation_requests": 4,
    "queued_messages": 500,
    "stored_products": 5000,
    "training_jobs": 1,
    "concurrent_training_jobs": 1,
    "maximum_training_duration_minutes": 30,
    "active_model_versions": 2,
    "maximum_inference_replicas": 1,
    "artifact_storage_bytes": 1073741824,
}


def _create_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_select ON "{table}"
        FOR SELECT TO graphrec_app
        USING (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_insert ON "{table}"
        FOR INSERT TO graphrec_app
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "pricing_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("limits", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','suspended','deleting','deleted')",
            name="ck_tenants_status",
        ),
    )
    op.create_table(
        "tenant_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("credential_digest", sa.Text()),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "email", name="uq_tenant_users_tenant_email"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tenant_users_tenant_id_id"),
        sa.CheckConstraint(
            "role IN ('tenant_administrator','tenant_developer')",
            name="ck_tenant_users_role",
        ),
        sa.CheckConstraint(
            "status IN ('invited','active','locked','disabled')",
            name="ck_tenant_users_status",
        ),
    )
    op.create_index("ix_tenant_users_tenant_status", "tenant_users", ["tenant_id", "status"])
    op.create_table(
        "tenant_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pricing_plans.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("project_defaults", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("period_end > period_start", name="ck_subscription_period"),
        sa.CheckConstraint("status IN ('active')", name="ck_subscription_status_current_slice"),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_current_subscription"),
    )
    op.create_table(
        "tenant_resource_quotas",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("limits", postgresql.JSONB(), nullable=False),
        sa.Column("overrides", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("actor_reference", postgresql.UUID(as_uuid=True)),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_reference", postgresql.UUID(as_uuid=True)),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("correlation_reference", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("redacted_details", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_tenant_time", "audit_logs", ["tenant_id", "occurred_at"])
    op.create_table(
        "registration_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        ),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("sanitized_detail", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_security_events_severity_time", "security_events", ["severity", "occurred_at"]
    )

    plans = sa.table(
        "pricing_plans",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("limits", postgresql.JSONB()),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        plans,
        [{"id": FREE_PLAN_ID, "code": "free", "name": "Free demo", "limits": FREE_LIMITS, "is_active": True}],
    )

    op.execute("GRANT USAGE ON SCHEMA public TO graphrec_app")
    op.execute("GRANT SELECT ON pricing_plans TO graphrec_app")
    op.execute("GRANT INSERT ON tenants TO graphrec_app")
    op.execute("GRANT SELECT, INSERT ON registration_requests TO graphrec_app")
    op.execute("GRANT INSERT ON security_events TO graphrec_app")
    for table in ("tenant_users", "tenant_subscriptions", "tenant_resource_quotas", "audit_logs"):
        op.execute(f'GRANT SELECT, INSERT ON "{table}" TO graphrec_app')
        _create_rls(table)


def downgrade() -> None:
    for table in ("audit_logs", "tenant_resource_quotas", "tenant_subscriptions", "tenant_users"):
        op.execute(f'DROP POLICY IF EXISTS {table}_tenant_insert ON "{table}"')
        op.execute(f'DROP POLICY IF EXISTS {table}_tenant_select ON "{table}"')
    op.drop_index("ix_security_events_severity_time", table_name="security_events")
    op.drop_table("security_events")
    op.drop_table("registration_requests")
    op.drop_index("ix_audit_logs_tenant_time", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("tenant_resource_quotas")
    op.drop_table("tenant_subscriptions")
    op.drop_index("ix_tenant_users_tenant_status", table_name="tenant_users")
    op.drop_table("tenant_users")
    op.drop_table("tenants")
    op.drop_table("pricing_plans")
