"""Plan change requests: tenants ask for a plan, a platform operator approves it.

GraphRec takes no payments, so a tenant cannot switch plans by itself. A tenant
administrator files a request for any active plan other than its current one
(Free demo, Basic, Pro); an operator with the plan-management role approves or
rejects it. Approval activates the plan in the same transaction through
``platform_assign_plan`` (migration 0018), so a request can never be approved
without the plan changing, or the plan change without the request closing.

Requests are tenant data (RLS): a tenant sees and files only its own and may
cancel its own pending request. Operators work across tenants through the
SECURITY DEFINER functions below, like the other platform functions.
"""
from alembic import op

revision = "0039_plan_change_requests"
down_revision = "0038_metrics_aggregates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE plan_change_requests (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      current_plan_id uuid NOT NULL REFERENCES pricing_plans(id),
      requested_plan_id uuid NOT NULL REFERENCES pricing_plans(id),
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
      message text CHECK (message IS NULL OR length(message) <= 500),
      requested_by text,
      decision_reason text CHECK (decision_reason IS NULL OR length(decision_reason) <= 500),
      decided_by uuid REFERENCES platform_operators(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      decided_at timestamptz,
      CHECK (requested_plan_id <> current_plan_id),
      CHECK ((status = 'pending') = (decided_at IS NULL))
    );
    -- At most one open request per tenant.
    CREATE UNIQUE INDEX uq_plan_change_requests_one_pending
      ON plan_change_requests (tenant_id) WHERE status = 'pending';
    CREATE INDEX ix_plan_change_requests_tenant_created ON plan_change_requests (tenant_id, created_at DESC);
    CREATE INDEX ix_plan_change_requests_status_created ON plan_change_requests (status, created_at);

    ALTER TABLE plan_change_requests ENABLE ROW LEVEL SECURITY;
    ALTER TABLE plan_change_requests FORCE ROW LEVEL SECURITY;
    CREATE POLICY plan_change_requests_tenant_select ON plan_change_requests FOR SELECT TO graphrec_app
      USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
    CREATE POLICY plan_change_requests_tenant_insert ON plan_change_requests FOR INSERT TO graphrec_app
      WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
                  AND status = 'pending');
    -- A tenant may only withdraw its own pending request.
    CREATE POLICY plan_change_requests_tenant_cancel ON plan_change_requests FOR UPDATE TO graphrec_app
      USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid AND status = 'pending')
      WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
                  AND status = 'cancelled');
    GRANT SELECT, INSERT ON plan_change_requests TO graphrec_app;
    GRANT UPDATE (status, decided_at) ON plan_change_requests TO graphrec_app;

    CREATE FUNCTION public.platform_list_plan_requests(p_status text)
    RETURNS TABLE (id uuid, tenant_id uuid, tenant_slug text, tenant_name text,
                   current_plan_code text, current_plan_name text,
                   requested_plan_id uuid, requested_plan_code text, requested_plan_name text,
                   active_plan_code text, status text, message text, requested_by text,
                   decision_reason text, decided_by uuid, decided_by_email text,
                   created_at timestamptz, decided_at timestamptz)
    LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $$
      SELECT r.id, r.tenant_id, t.slug::text, t.name, cp.code::text, cp.name, r.requested_plan_id,
             rp.code::text, rp.name, ap.code::text, r.status, r.message, r.requested_by,
             r.decision_reason, r.decided_by, o.email::text, r.created_at, r.decided_at
      FROM public.plan_change_requests r
      JOIN public.tenants t ON t.id = r.tenant_id
      JOIN public.pricing_plans cp ON cp.id = r.current_plan_id
      JOIN public.pricing_plans rp ON rp.id = r.requested_plan_id
      LEFT JOIN public.tenant_subscriptions s ON s.tenant_id = r.tenant_id
      LEFT JOIN public.pricing_plans ap ON ap.id = s.plan_id
      LEFT JOIN public.platform_operators o ON o.id = r.decided_by
      WHERE p_status IS NULL OR r.status = p_status
      ORDER BY (r.status = 'pending') DESC, CASE WHEN r.status = 'pending' THEN r.created_at END ASC,
               r.decided_at DESC NULLS LAST
      LIMIT 500
    $$;

    -- Approve (activating the plan) or reject one pending request. Returns the
    -- tenant id, or NULL when the request does not exist or is no longer pending.
    CREATE FUNCTION public.platform_decide_plan_request(p_request_id uuid, p_approve boolean, p_reason text,
                                                        p_operator_id uuid, p_correlation_id uuid)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE req public.plan_change_requests%ROWTYPE;
    BEGIN
      SELECT * INTO req FROM public.plan_change_requests WHERE id = p_request_id FOR UPDATE;
      IF NOT FOUND OR req.status <> 'pending' THEN RETURN NULL; END IF;
      IF p_approve THEN
        IF NOT public.platform_assign_plan(req.tenant_id, req.requested_plan_id, p_correlation_id) THEN
          RAISE EXCEPTION 'plan_not_assignable' USING ERRCODE = 'P0001';
        END IF;
      END IF;
      UPDATE public.plan_change_requests
         SET status = CASE WHEN p_approve THEN 'approved' ELSE 'rejected' END,
             decision_reason = NULLIF(btrim(p_reason), ''), decided_by = p_operator_id, decided_at = now()
       WHERE id = p_request_id;
      INSERT INTO public.audit_logs (id, tenant_id, actor_type, actor_reference, action_type, resource_type,
        resource_reference, outcome, correlation_reference, redacted_details, occurred_at)
      VALUES (gen_random_uuid(), req.tenant_id, 'platform_administrator', p_operator_id,
        CASE WHEN p_approve THEN 'plan_request.approved' ELSE 'plan_request.rejected' END,
        'plan_change_request', req.id, 'succeeded', p_correlation_id,
        jsonb_build_object('requested_plan_id', req.requested_plan_id, 'current_plan_id', req.current_plan_id),
        now());
      RETURN req.tenant_id;
    END $$;

    CREATE FUNCTION public.platform_pending_plan_request_count() RETURNS integer
    LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $$
      SELECT count(*)::integer FROM public.plan_change_requests WHERE status = 'pending'
    $$;

    REVOKE ALL ON FUNCTION public.platform_list_plan_requests(text) FROM PUBLIC;
    REVOKE ALL ON FUNCTION public.platform_decide_plan_request(uuid, boolean, text, uuid, uuid) FROM PUBLIC;
    REVOKE ALL ON FUNCTION public.platform_pending_plan_request_count() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION public.platform_list_plan_requests(text) TO graphrec_app;
    GRANT EXECUTE ON FUNCTION public.platform_decide_plan_request(uuid, boolean, text, uuid, uuid) TO graphrec_app;
    GRANT EXECUTE ON FUNCTION public.platform_pending_plan_request_count() TO graphrec_app;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION public.platform_pending_plan_request_count()")
    op.execute("DROP FUNCTION public.platform_decide_plan_request(uuid, boolean, text, uuid, uuid)")
    op.execute("DROP FUNCTION public.platform_list_plan_requests(text)")
    op.execute("DROP TABLE plan_change_requests")
