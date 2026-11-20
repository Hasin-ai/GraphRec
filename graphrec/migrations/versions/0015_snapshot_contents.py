"""Store immutable tenant snapshot contents, rather than a fictional object URI."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
from alembic import op

revision = "0015_snapshot_contents"
down_revision = "0014_recommendation_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("dataset_snapshot_contents",
        sa.Column("snapshot_id", pg.UUID(as_uuid=True), sa.ForeignKey("dataset_snapshots.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", pg.JSONB(), nullable=False))
    op.execute("ALTER TABLE dataset_snapshot_contents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dataset_snapshot_contents FORCE ROW LEVEL SECURITY")
    predicate = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(f"CREATE POLICY snapshot_content_select ON dataset_snapshot_contents FOR SELECT TO graphrec_app USING ({predicate})")
    op.execute(f"CREATE POLICY snapshot_content_insert ON dataset_snapshot_contents FOR INSERT TO graphrec_app WITH CHECK ({predicate})")
    op.execute("GRANT SELECT, INSERT ON dataset_snapshot_contents TO graphrec_app")


def downgrade():
    op.drop_table("dataset_snapshot_contents")
