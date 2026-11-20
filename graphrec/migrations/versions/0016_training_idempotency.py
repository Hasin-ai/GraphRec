"""Tenant-local retry identity for training and checkpoint imports."""
import sqlalchemy as sa
from alembic import op

revision = "0016_training_idempotency"
down_revision = "0015_snapshot_contents"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("training_jobs", sa.Column("request_id", sa.String(128)))
    op.add_column("training_jobs", sa.Column("payload_hash", sa.String(64)))
    op.create_unique_constraint("uq_training_jobs_tenant_request", "training_jobs", ["tenant_id", "request_id"])


def downgrade():
    op.drop_constraint("uq_training_jobs_tenant_request", "training_jobs", type_="unique")
    op.drop_column("training_jobs", "payload_hash")
    op.drop_column("training_jobs", "request_id")
