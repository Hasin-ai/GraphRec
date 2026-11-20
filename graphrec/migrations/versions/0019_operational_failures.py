"""Include redacted lifecycle failures and authenticated denials in monitoring."""
from alembic import op

revision = "0019_operational_failures"
down_revision = "0018_platform_plan_assignment"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION public.platform_recent_security_events(p_limit integer)
    RETURNS TABLE(id uuid, tenant_id uuid, event_type text, severity text, sanitized_detail jsonb, occurred_at timestamptz)
    LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $$
      SELECT * FROM (
        SELECT e.id, e.tenant_id, e.event_type::text, e.severity::text, e.sanitized_detail, e.occurred_at
        FROM public.security_events e
        UNION ALL
        SELECT a.id, a.tenant_id, a.action_type::text,
          CASE WHEN a.outcome = 'denied' THEN 'warning' ELSE 'error' END, a.redacted_details, a.occurred_at
        FROM public.audit_logs a WHERE a.outcome IN ('failed', 'failure', 'denied')
      ) combined ORDER BY occurred_at DESC LIMIT LEAST(GREATEST(p_limit, 1), 500)
    $$;
    """)


def downgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION public.platform_recent_security_events(p_limit integer)
    RETURNS TABLE(id uuid, tenant_id uuid, event_type text, severity text, sanitized_detail jsonb, occurred_at timestamptz)
    LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $$
      SELECT e.id, e.tenant_id, e.event_type::text, e.severity::text, e.sanitized_detail, e.occurred_at
      FROM public.security_events e ORDER BY e.occurred_at DESC LIMIT LEAST(GREATEST(p_limit, 1), 500)
    $$;
    """)
