"""A-09 / ER-F-11: reasons in the audit trail.

A request that changes state may carry a human reason (tenant status change,
plan or quota change, activation, rollback, archive, cancellation). The API
puts it in the transaction-local setting ``app.audit_reason``; this trigger
copies it into ``redacted_details.justification`` (``reason`` already holds
machine failure causes such as ``model_not_ready``) of every audit row written in that
transaction, including rows written by the SECURITY DEFINER platform functions.
``app.audit_actor`` is reserved for an operator identity (decision D-04) and,
when set, fills an empty ``actor_reference``. The table stays append-only.

``platform_audit_search`` adds the UC-31 filters (tenant, action, outcome,
time range) with keyset pagination, and returns actor, reason and correlation id.
"""

from alembic import op

revision = "0034_audit_reasons"
down_revision = "0033_registration_requests_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE FUNCTION public.audit_attach_context() RETURNS trigger
      LANGUAGE plpgsql SET search_path = pg_catalog, public AS $function$
      DECLARE
        v_reason text := NULLIF(current_setting('app.audit_reason', true), '');
        v_actor text := NULLIF(current_setting('app.audit_actor', true), '');
      BEGIN
        IF v_reason IS NOT NULL AND NOT (COALESCE(NEW.redacted_details, '{}'::jsonb) ? 'justification') THEN
          NEW.redacted_details := COALESCE(NEW.redacted_details, '{}'::jsonb)
            || jsonb_build_object('justification', left(v_reason, 500));
        END IF;
        IF v_actor IS NOT NULL AND NEW.actor_reference IS NULL THEN
          NEW.actor_reference := v_actor::uuid;
        END IF;
        RETURN NEW;
      END;
      $function$
    """)
    op.execute("""
      CREATE TRIGGER audit_logs_attach_context BEFORE INSERT ON public.audit_logs
      FOR EACH ROW EXECUTE FUNCTION public.audit_attach_context()
    """)


    op.execute("""
      CREATE FUNCTION public.platform_audit_search(
        p_tenant_id uuid, p_action text, p_outcome text,
        p_since timestamptz, p_until timestamptz, p_before timestamptz, p_limit integer)
      RETURNS TABLE(id uuid, tenant_id uuid, actor_type text, actor_reference uuid, action_type text,
        resource_type text, resource_reference uuid, outcome text, correlation_reference uuid,
        reason text, occurred_at timestamptz)
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $function$
        SELECT a.id, a.tenant_id, a.actor_type::text, a.actor_reference, a.action_type::text,
               a.resource_type::text, a.resource_reference, a.outcome::text, a.correlation_reference,
               a.redacted_details->>'justification', a.occurred_at
        FROM public.audit_logs a
        WHERE (p_tenant_id IS NULL OR a.tenant_id = p_tenant_id)
          AND (p_action IS NULL OR a.action_type = p_action)
          AND (p_outcome IS NULL OR a.outcome = p_outcome)
          AND (p_since IS NULL OR a.occurred_at >= p_since)
          AND (p_until IS NULL OR a.occurred_at < p_until)
          AND (p_before IS NULL OR a.occurred_at < p_before)
        ORDER BY a.occurred_at DESC
        LIMIT LEAST(GREATEST(p_limit, 1), 500)
      $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.platform_audit_search(uuid, text, text, timestamptz, timestamptz, timestamptz, integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.platform_audit_search(uuid, text, text, timestamptz, timestamptz, timestamptz, integer) TO graphrec_app")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_occurred ON audit_logs(occurred_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_audit_logs_occurred")
    op.execute("DROP FUNCTION IF EXISTS public.platform_audit_search(uuid, text, text, timestamptz, timestamptz, timestamptz, integer)")
    op.execute("DROP TRIGGER audit_logs_attach_context ON public.audit_logs")
    op.execute("DROP FUNCTION public.audit_attach_context()")
