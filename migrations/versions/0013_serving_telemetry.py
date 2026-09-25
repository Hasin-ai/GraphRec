"""append-only serving request ledger behind /v1/metrics/summary

The metrics endpoint previously returned constants. Request rate, error rate,
fallback rate and p95 latency are now measured from this table, which records
one row per recommendation request handled by the API.

Revision ID: 0013_serving_telemetry
Revises: 0012_basic_pro_plans
Create Date: 2026-09-13
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_serving_telemetry"
down_revision: Union[str, None] = "0012_basic_pro_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "serving_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("outcome IN ('served','error')", name="ck_serving_requests_outcome"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_serving_requests_latency"),
    )
    op.create_index(
        "ix_serving_requests_tenant_occurred", "serving_requests", ["tenant_id", "occurred_at"]
    )

    op.execute("ALTER TABLE serving_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE serving_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY serving_requests_tenant_select ON serving_requests
        FOR SELECT TO graphrec_app
        USING ({TENANT_PREDICATE})
        """
    )
    op.execute(
        f"""
        CREATE POLICY serving_requests_tenant_insert ON serving_requests
        FOR INSERT TO graphrec_app
        WITH CHECK ({TENANT_PREDICATE})
        """
    )
    # Append-only, like the usage ledger: no UPDATE or DELETE grant.
    op.execute("GRANT SELECT, INSERT ON serving_requests TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS serving_requests_tenant_insert ON serving_requests")
    op.execute("DROP POLICY IF EXISTS serving_requests_tenant_select ON serving_requests")
    op.drop_index("ix_serving_requests_tenant_occurred", table_name="serving_requests")
    op.drop_table("serving_requests")
