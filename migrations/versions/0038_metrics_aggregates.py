"""ER-NF-09: platform-wide aggregate counts for /metrics.

Returns only counts (no tenant ids, no rows), so exposing it to the runtime role
does not weaken tenant isolation.
"""

from alembic import op

revision = "0038_metrics_aggregates"
down_revision = "0037_tenant_user_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE FUNCTION public.platform_metrics_aggregates() RETURNS jsonb
      LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $function$
        SELECT jsonb_build_object(
          'training_queued', (SELECT count(*) FROM public.training_jobs WHERE status = 'queued'),
          'training_running', (SELECT count(*) FROM public.training_jobs WHERE status = 'running'),
          'tenants_active', (SELECT count(*) FROM public.tenants WHERE status = 'active'),
          'tenants_suspended', (SELECT count(*) FROM public.tenants WHERE status = 'suspended'),
          'active_model_versions', (SELECT count(*) FROM public.model_versions WHERE status = 'active')
        )
      $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.platform_metrics_aggregates() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.platform_metrics_aggregates() TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.platform_metrics_aggregates()")
