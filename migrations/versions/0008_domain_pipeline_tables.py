"""create domain pipeline tables and grant graphrec_app privileges

Revision ID: 0008_domain_pipeline_tables
Revises: 0007_allow_user_password_setup
Create Date: 2026-08-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_domain_pipeline_tables"
down_revision: Union[str, None] = "0007_allow_user_password_setup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("availability_status", sa.String(32), nullable=False, server_default="available"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "external_id", name="uq_products_tenant_external"),
    )
    op.create_index("ix_products_tenant_active", "products", ["tenant_id", "is_active"])

    op.create_table(
        "customer_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("external_product_id", sa.String(100), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "event_id", name="uq_customer_events_tenant_event"),
    )
    op.create_index(
        "ix_customer_events_tenant_time", "customer_events", ["tenant_id", "occurred_at"]
    )

    op.create_table(
        "event_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_event_batches_tenant_created", "event_batches", ["tenant_id", "created_at"]
    )

    op.create_table(
        "model_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_tag", sa.String(64), nullable=False),
        sa.Column("model_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="eligible"),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("artifact_uri", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "version_tag", name="uq_model_versions_tenant_tag"),
    )
    op.create_index("ix_model_versions_tenant_status", "model_versions", ["tenant_id", "status"])

    op.create_table(
        "training_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="succeeded"),
        sa.Column("configuration", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_training_jobs_tenant_created", "training_jobs", ["tenant_id", "created_at"]
    )

    op.create_table(
        "dataset_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("training_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("product_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifact_uri", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_dataset_snapshots_tenant_created", "dataset_snapshots", ["tenant_id", "created_at"]
    )

    op.execute("REVOKE DELETE ON api_keys FROM graphrec_app")
    op.execute("REVOKE UPDATE, DELETE ON usage_events FROM graphrec_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON products, customer_events, event_batches, model_versions, training_jobs, dataset_snapshots TO graphrec_app")


def downgrade() -> None:
    op.drop_table("dataset_snapshots")
    op.drop_table("training_jobs")
    op.drop_table("model_versions")
    op.drop_table("event_batches")
    op.drop_table("customer_events")
    op.drop_table("products")
