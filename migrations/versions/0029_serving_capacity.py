"""XR-F-08 / XR-NF-01: metrics-driven serving capacity with observable scaling events."""

from alembic import op

revision = "0029_serving_capacity"
down_revision = "0028_recommendation_policies"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("ALTER TABLE model_deployments DROP CONSTRAINT ck_deployment_capacity")
    op.execute("""ALTER TABLE model_deployments ADD CONSTRAINT ck_deployment_capacity
      CHECK (desired_capacity BETWEEN 1 AND 100 AND ready_capacity BETWEEN 0 AND desired_capacity)""")
    op.execute("ALTER TABLE model_deployments ADD COLUMN last_scaled_at timestamptz")
    op.execute("""
      CREATE TABLE capacity_events (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        model_version_id uuid,
        from_capacity integer NOT NULL,
        to_capacity integer NOT NULL,
        reason varchar(32) NOT NULL,
        measured_rpm integer NOT NULL,
        peak_rpm integer NOT NULL,
        max_capacity integer NOT NULL,
        occurred_at timestamptz NOT NULL,
        CONSTRAINT ck_capacity_event_reason CHECK (reason IN ('scale_up','scale_down','limit_clamp'))
      )
    """)
    op.execute("CREATE INDEX ix_capacity_events_tenant_time ON capacity_events(tenant_id, occurred_at DESC)")
    op.execute("ALTER TABLE capacity_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE capacity_events FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY capacity_events_select ON capacity_events FOR SELECT TO graphrec_app USING ({TENANT})")
    op.execute(f"CREATE POLICY capacity_events_insert ON capacity_events FOR INSERT TO graphrec_app WITH CHECK ({TENANT})")
    op.execute("GRANT SELECT, INSERT ON capacity_events TO graphrec_app")
    op.execute("""
      CREATE FUNCTION public.capacity_controller_tenants() RETURNS SETOF uuid
      LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $function$
        SELECT d.tenant_id FROM public.model_deployments d JOIN public.tenants t ON t.id = d.tenant_id
        WHERE t.status = 'active' AND d.active_model_version_id IS NOT NULL
      $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.capacity_controller_tenants() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.capacity_controller_tenants() TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.capacity_controller_tenants()")
    op.execute("DROP TABLE capacity_events")
    op.execute("ALTER TABLE model_deployments DROP COLUMN last_scaled_at")
    op.execute("UPDATE model_deployments SET desired_capacity = 1, ready_capacity = LEAST(ready_capacity, 1)")
    op.execute("ALTER TABLE model_deployments DROP CONSTRAINT ck_deployment_capacity")
    op.execute("""ALTER TABLE model_deployments ADD CONSTRAINT ck_deployment_capacity
      CHECK (desired_capacity = 1 AND ready_capacity BETWEEN 0 AND 1)""")
