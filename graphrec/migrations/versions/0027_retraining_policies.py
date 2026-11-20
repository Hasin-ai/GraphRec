"""XR-F-02/XR-F-03: per-tenant scheduled and event-triggered retraining policies."""

from alembic import op

revision = "0027_retraining_policies"
down_revision = "0026_customers"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
      CREATE TABLE retraining_policies (
        tenant_id uuid PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
        schedule_enabled boolean NOT NULL DEFAULT false,
        interval_minutes integer NOT NULL DEFAULT 1440,
        next_run_at timestamptz,
        event_trigger_enabled boolean NOT NULL DEFAULT false,
        event_threshold integer NOT NULL DEFAULT 1000,
        epochs integer NOT NULL DEFAULT 3,
        last_evaluated_at timestamptz,
        last_trigger varchar(16),
        last_outcome varchar(48),
        last_outcome_detail text,
        last_outcome_at timestamptz,
        last_job_id uuid,
        updated_at timestamptz NOT NULL,
        CONSTRAINT ck_retraining_interval CHECK (interval_minutes BETWEEN 1 AND 43200),
        CONSTRAINT ck_retraining_threshold CHECK (event_threshold BETWEEN 1 AND 10000000),
        CONSTRAINT ck_retraining_epochs CHECK (epochs BETWEEN 1 AND 10),
        CONSTRAINT ck_retraining_trigger CHECK (last_trigger IS NULL OR last_trigger IN ('schedule','events'))
      )
    """)
    op.execute("ALTER TABLE retraining_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE retraining_policies FORCE ROW LEVEL SECURITY")
    for verb, clause in (("SELECT", f"USING ({TENANT})"), ("INSERT", f"WITH CHECK ({TENANT})"),
                         ("UPDATE", f"USING ({TENANT}) WITH CHECK ({TENANT})")):
        op.execute(f"CREATE POLICY retraining_policies_{verb.lower()} ON retraining_policies FOR {verb} TO graphrec_app {clause}")
    op.execute("GRANT SELECT, INSERT, UPDATE ON retraining_policies TO graphrec_app")
    # The scheduler must discover which tenants have an enabled policy without
    # reading any tenant's rows directly (RLS); it then works inside each tenant.
    op.execute("""
      CREATE FUNCTION public.retraining_policy_tenants() RETURNS SETOF uuid
      LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $function$
        SELECT p.tenant_id FROM public.retraining_policies p JOIN public.tenants t ON t.id = p.tenant_id
        WHERE t.status = 'active' AND (p.schedule_enabled OR p.event_trigger_enabled)
      $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.retraining_policy_tenants() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.retraining_policy_tenants() TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.retraining_policy_tenants()")
    op.execute("DROP TABLE retraining_policies")
