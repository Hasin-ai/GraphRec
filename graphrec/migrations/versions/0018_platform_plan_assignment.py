"""Read tenant quota configuration and audit platform plan assignments."""
from alembic import op

revision = "0018_platform_plan_assignment"
down_revision = "0017_training_worker"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION public.platform_tenant_plan(p_tenant_id uuid) RETURNS jsonb
    LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $$
      SELECT jsonb_build_object('plan_id', p.id, 'plan_code', p.code, 'plan_limits', p.limits,
        'quota_limits', q.limits, 'overrides', q.overrides)
      FROM public.tenant_subscriptions s JOIN public.pricing_plans p ON p.id = s.plan_id
      JOIN public.tenant_resource_quotas q ON q.tenant_id = s.tenant_id
      WHERE s.tenant_id = p_tenant_id
    $$;
    CREATE FUNCTION public.platform_assign_plan(p_tenant_id uuid, p_plan_id uuid, p_correlation_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE new_limits jsonb; old_plan uuid;
    BEGIN
      SELECT p.limits INTO new_limits FROM public.pricing_plans p WHERE p.id = p_plan_id AND p.is_active;
      IF NOT FOUND THEN RETURN false; END IF;
      SELECT s.plan_id INTO old_plan FROM public.tenant_subscriptions s WHERE s.tenant_id = p_tenant_id FOR UPDATE;
      IF NOT FOUND THEN RETURN false; END IF;
      UPDATE public.tenant_subscriptions SET plan_id = p_plan_id WHERE tenant_id = p_tenant_id;
      UPDATE public.tenant_resource_quotas SET limits = new_limits WHERE tenant_id = p_tenant_id;
      INSERT INTO public.audit_logs (id, tenant_id, actor_type, actor_reference, action_type, resource_type,
        resource_reference, outcome, correlation_reference, redacted_details, occurred_at)
      VALUES (gen_random_uuid(), p_tenant_id, 'platform_administrator', NULL, 'tenant.plan_changed',
        'tenant_subscription', p_tenant_id, 'succeeded', p_correlation_id,
        jsonb_build_object('previous_plan_id', old_plan, 'plan_id', p_plan_id), now());
      RETURN true;
    END $$;
    REVOKE ALL ON FUNCTION public.platform_tenant_plan(uuid) FROM PUBLIC;
    REVOKE ALL ON FUNCTION public.platform_assign_plan(uuid, uuid, uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION public.platform_tenant_plan(uuid) TO graphrec_app;
    GRANT EXECUTE ON FUNCTION public.platform_assign_plan(uuid, uuid, uuid) TO graphrec_app;
    """)


def downgrade():
    op.execute("DROP FUNCTION public.platform_assign_plan(uuid, uuid, uuid)")
    op.execute("DROP FUNCTION public.platform_tenant_plan(uuid)")
