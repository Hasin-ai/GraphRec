"""Track desired and last ready model independently of version metadata."""

from alembic import op

revision = "0023_model_deployments"
down_revision = "0022_durable_ingestion"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX uq_model_versions_tenant_id ON model_versions(tenant_id, id)")
    op.execute("""
      CREATE TABLE model_deployments (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
        desired_model_version_id uuid,
        active_model_version_id uuid,
        status varchar(24) NOT NULL,
        desired_capacity integer NOT NULL DEFAULT 1,
        ready_capacity integer NOT NULL DEFAULT 0,
        last_transition_at timestamptz NOT NULL,
        failure_reason text,
        CONSTRAINT fk_deployment_desired FOREIGN KEY (tenant_id, desired_model_version_id)
          REFERENCES model_versions(tenant_id, id),
        CONSTRAINT fk_deployment_active FOREIGN KEY (tenant_id, active_model_version_id)
          REFERENCES model_versions(tenant_id, id),
        CONSTRAINT ck_deployment_status CHECK (status IN ('pending','progressing','available','degraded','rolling_back','stopped')),
        CONSTRAINT ck_deployment_capacity CHECK (desired_capacity = 1 AND ready_capacity BETWEEN 0 AND 1)
      )
    """)
    op.execute("""
      INSERT INTO model_deployments (id, tenant_id, desired_model_version_id, active_model_version_id,
        status, desired_capacity, ready_capacity, last_transition_at)
      SELECT gen_random_uuid(), tenant_id, id, id, 'available', 1, 1,
        COALESCE(activated_at, created_at) FROM model_versions WHERE status = 'active'
    """)
    op.execute("ALTER TABLE model_deployments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE model_deployments FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY model_deployments_select ON model_deployments FOR SELECT TO graphrec_app USING ({TENANT})")
    op.execute(f"CREATE POLICY model_deployments_insert ON model_deployments FOR INSERT TO graphrec_app WITH CHECK ({TENANT})")
    op.execute(f"CREATE POLICY model_deployments_update ON model_deployments FOR UPDATE TO graphrec_app USING ({TENANT}) WITH CHECK ({TENANT})")
    op.execute("GRANT SELECT, INSERT, UPDATE ON model_deployments TO graphrec_app")
    op.execute("""
      CREATE FUNCTION public.platform_deployment_capacity() RETURNS jsonb
      LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $function$
        SELECT jsonb_build_object(
          'available_tenants', count(*) FILTER (WHERE status = 'available'),
          'degraded_tenants', count(*) FILTER (WHERE status = 'degraded'),
          'desired_capacity', COALESCE(sum(desired_capacity), 0),
          'ready_capacity', COALESCE(sum(ready_capacity), 0)
        ) FROM public.model_deployments
      $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.platform_deployment_capacity() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.platform_deployment_capacity() TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.platform_deployment_capacity()")
    op.execute("DROP TABLE model_deployments")
    op.execute("DROP INDEX uq_model_versions_tenant_id")
