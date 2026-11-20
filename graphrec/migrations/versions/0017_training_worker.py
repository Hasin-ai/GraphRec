"""Durable bounded training queue and worker progress."""
import sqlalchemy as sa
from alembic import op

revision = "0017_training_worker"
down_revision = "0016_training_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("training_jobs", sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("training_jobs", sa.Column("stage", sa.String(40), nullable=False, server_default="completed"))
    op.add_column("training_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column("training_jobs", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("training_jobs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.execute("""
    CREATE FUNCTION public.claim_training_job() RETURNS TABLE(job_id uuid, owner_tenant_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    BEGIN
      UPDATE public.training_jobs SET status = CASE WHEN attempts < 2 THEN 'queued' ELSE 'failed' END,
        failure_reason = CASE WHEN attempts < 2 THEN NULL ELSE 'worker_interrupted: retry budget exhausted' END,
        completed_at = CASE WHEN attempts < 2 THEN NULL ELSE now() END
      WHERE status = 'running' AND configuration->>'mode' = 'train'
        AND heartbeat_at < now() - interval '5 minutes';
      RETURN QUERY
      UPDATE public.training_jobs j SET status = 'running', stage = 'preparing',
        heartbeat_at = now(), attempts = attempts + 1
      WHERE j.id = (SELECT q.id FROM public.training_jobs q JOIN public.tenants t ON t.id = q.tenant_id
        WHERE q.status = 'queued' AND q.configuration->>'mode' = 'train' AND t.status = 'active'
        ORDER BY q.created_at FOR UPDATE OF q SKIP LOCKED LIMIT 1)
      RETURNING j.id, j.tenant_id;
    END $$;
    REVOKE ALL ON FUNCTION public.claim_training_job() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION public.claim_training_job() TO graphrec_app;
    """)


def downgrade():
    op.execute("DROP FUNCTION public.claim_training_job()")
    for name in ("attempts", "cancel_requested", "heartbeat_at", "stage", "progress"):
        op.drop_column("training_jobs", name)
