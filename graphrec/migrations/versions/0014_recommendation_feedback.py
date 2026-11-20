"""Persist tenant-scoped recommendation results and idempotent feedback."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
from alembic import op

revision = "0014_recommendation_feedback"
down_revision = "0013_serving_telemetry"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recommendation_records",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("response", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("recommendation_feedback",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("feedback_type", sa.String(16), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "request_id"], ["recommendation_records.tenant_id", "recommendation_records.request_id"]))
    for table in ("recommendation_records", "recommendation_feedback"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        predicate = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute(f"CREATE POLICY {table}_select ON {table} FOR SELECT TO graphrec_app USING ({predicate})")
        op.execute(f"CREATE POLICY {table}_insert ON {table} FOR INSERT TO graphrec_app WITH CHECK ({predicate})")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO graphrec_app")


def downgrade():
    op.drop_table("recommendation_feedback")
    op.drop_table("recommendation_records")
