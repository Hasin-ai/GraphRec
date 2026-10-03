"""Allow audited, bounded edits to platform plan definitions."""

from alembic import op

revision = "0020_platform_plan_edit"
down_revision = "0019_operational_failures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION public.platform_update_plan(
      p_plan_id uuid, p_name text, p_limits jsonb, p_active boolean, p_correlation_id uuid
    ) RETURNS TABLE(id uuid, code text, name text, limits jsonb, is_active boolean)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE previous_limits jsonb; previous_name text; previous_active boolean;
    BEGIN
      SELECT p.limits, p.name, p.is_active INTO previous_limits, previous_name, previous_active
      FROM public.pricing_plans p WHERE p.id = p_plan_id FOR UPDATE;
      IF NOT FOUND THEN RETURN; END IF;
      IF p_name IS NULL OR length(btrim(p_name)) = 0 OR length(p_name) > 100
         OR p_active IS NULL OR jsonb_typeof(p_limits) <> 'object'
         OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_limits) k)
            IS DISTINCT FROM (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(previous_limits) k)
         OR EXISTS (SELECT 1 FROM jsonb_each(p_limits) AS entry(k, v)
                    WHERE jsonb_typeof(v) <> 'number' OR v::text !~ '^[0-9]{1,16}$'
                      OR (v::text)::bigint > 9000000000000000)
      THEN RAISE EXCEPTION 'invalid plan update' USING ERRCODE = '22023'; END IF;
      UPDATE public.pricing_plans p SET name = btrim(p_name), limits = p_limits, is_active = p_active
      WHERE p.id = p_plan_id;
      UPDATE public.tenant_resource_quotas q SET limits = p_limits
      FROM public.tenant_subscriptions s
      WHERE q.tenant_id = s.tenant_id AND s.plan_id = p_plan_id;
      INSERT INTO public.audit_logs (id, tenant_id, actor_type, actor_reference, action_type,
        resource_type, resource_reference, outcome, correlation_reference, redacted_details, occurred_at)
      SELECT gen_random_uuid(), s.tenant_id, 'platform_administrator', NULL, 'plan.updated',
        'pricing_plan', p_plan_id, 'succeeded', p_correlation_id,
        jsonb_build_object('plan_id', p_plan_id, 'previous_name', previous_name,
          'name', p_name, 'previous_active', previous_active, 'active', p_active,
          'changed_limit_keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(p_limits) k
            WHERE p_limits->k IS DISTINCT FROM previous_limits->k)), now()
      FROM public.tenant_subscriptions s WHERE s.plan_id = p_plan_id;
      INSERT INTO public.security_events (id, tenant_id, event_type, severity, source_hash,
        sanitized_detail, occurred_at)
      VALUES (gen_random_uuid(), NULL, 'platform_plan_updated', 'info', repeat('0', 64),
        jsonb_build_object('plan_id', p_plan_id, 'correlation_id', p_correlation_id), now());
      RETURN QUERY SELECT p.id, p.code::text, p.name::text, p.limits, p.is_active
      FROM public.pricing_plans p WHERE p.id = p_plan_id;
    END $$;
    REVOKE ALL ON FUNCTION public.platform_update_plan(uuid, text, jsonb, boolean, uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION public.platform_update_plan(uuid, text, jsonb, boolean, uuid) TO graphrec_app;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION public.platform_update_plan(uuid, text, jsonb, boolean, uuid)")
