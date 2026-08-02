"""durable tenant usage ledger

Revision ID: 0004_usage_ledger
Revises: 0003_subscription_path
Create Date: 2026-08-01
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_usage_ledger"
down_revision: Union[str, None] = "0003_subscription_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("usage_type", sa.String(48), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 4), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_usage_events_tenant_idempotency"
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_events_quantity"),
        sa.CheckConstraint(
            "usage_type IN ('accepted_events','recommendation_requests','training_jobs',"
            "'training_cpu_seconds','stored_products','artifact_storage_bytes',"
            "'active_model_versions','inference_replicas','replica_runtime_minutes')",
            name="ck_usage_events_type",
        ),
    )
    op.create_index(
        "ix_usage_events_tenant_occurred",
        "usage_events",
        ["tenant_id", "occurred_at"],
    )
    op.execute("ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE usage_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY usage_events_tenant_select ON usage_events
        FOR SELECT TO graphrec_app
        USING (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY usage_events_tenant_insert ON usage_events
        FOR INSERT TO graphrec_app
        WITH CHECK (
          tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        """
    )
    op.execute("GRANT SELECT, INSERT ON usage_events TO graphrec_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT ON usage_events FROM graphrec_app")
    op.execute("DROP POLICY IF EXISTS usage_events_tenant_insert ON usage_events")
    op.execute("DROP POLICY IF EXISTS usage_events_tenant_select ON usage_events")
    op.drop_index("ix_usage_events_tenant_occurred", table_name="usage_events")
    op.drop_table("usage_events")
