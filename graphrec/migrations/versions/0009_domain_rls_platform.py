"""row-level security for domain pipeline tables and platform administrator functions

Revision ID: 0009_domain_rls_platform
Revises: 0008_domain_pipeline_tables
Create Date: 2026-09-11
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_domain_rls_platform"
down_revision: Union[str, None] = "0008_domain_pipeline_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DOMAIN_TABLES = (
    "products",
    "customer_events",
    "event_batches",
    "model_versions",
    "training_jobs",
    "dataset_snapshots",
)

TENANT_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"

PLATFORM_FUNCTIONS = (
    "platform_list_tenants()",
    "platform_set_tenant_status(uuid, text, uuid)",
    "platform_set_quota_overrides(uuid, jsonb, uuid)",
    "platform_recent_audit(integer)",
    "platform_recent_security_events(integer)",
)


def upgrade() -> None:
    op.add_column(
        "training_jobs",
        sa.Column("dataset_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    for table in DOMAIN_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        for operation in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            suffix = operation.lower()
            clauses = {
                "SELECT": f"USING ({TENANT_PREDICATE})",
                "INSERT": f"WITH CHECK ({TENANT_PREDICATE})",
                "UPDATE": f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})",
                "DELETE": f"USING ({TENANT_PREDICATE})",
            }
            op.execute(
                f"""
                CREATE POLICY {table}_tenant_{suffix} ON {table}
                FOR {operation} TO graphrec_app
                {clauses[operation]}
                """
            )

    # Platform administrator reads and writes cross tenant boundaries, so they run
    # through SECURITY DEFINER functions rather than widening graphrec_app grants.
    op.execute(
        """
        CREATE FUNCTION public.platform_list_tenants()
        RETURNS TABLE(id uuid, slug text, name text, status text, created_at timestamptz)
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $$
          SELECT t.id, t.slug::text, t.name, t.status::text, t.created_at
          FROM public.tenants AS t
          ORDER BY t.created_at DESC
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.platform_set_tenant_status(
          p_tenant_id uuid,
          p_status text,
          p_correlation_id uuid
        )
        RETURNS TABLE(id uuid, slug text, name text, status text, created_at timestamptz)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
          previous_status text;
        BEGIN
          SELECT t.status INTO previous_status FROM public.tenants AS t WHERE t.id = p_tenant_id;
          IF NOT FOUND THEN
            RETURN;
          END IF;
          UPDATE public.tenants AS t SET status = p_status WHERE t.id = p_tenant_id;
          INSERT INTO public.audit_logs (
            id, tenant_id, actor_type, actor_reference, action_type, resource_type,
            resource_reference, outcome, correlation_reference, redacted_details, occurred_at
          ) VALUES (
            gen_random_uuid(), p_tenant_id, 'platform_administrator', NULL,
            'tenant.status_changed', 'tenant', p_tenant_id, 'success', p_correlation_id,
            jsonb_build_object('from', previous_status, 'to', p_status), clock_timestamp()
          );
          RETURN QUERY
            SELECT t.id, t.slug::text, t.name, t.status::text, t.created_at
            FROM public.tenants AS t WHERE t.id = p_tenant_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.platform_set_quota_overrides(
          p_tenant_id uuid,
          p_overrides jsonb,
          p_correlation_id uuid
        )
        RETURNS TABLE(tenant_id uuid, limits jsonb, overrides jsonb)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
          UPDATE public.tenant_resource_quotas AS q
          SET overrides = p_overrides
          WHERE q.tenant_id = p_tenant_id;
          IF NOT FOUND THEN
            RETURN;
          END IF;
          INSERT INTO public.audit_logs (
            id, tenant_id, actor_type, actor_reference, action_type, resource_type,
            resource_reference, outcome, correlation_reference, redacted_details, occurred_at
          ) VALUES (
            gen_random_uuid(), p_tenant_id, 'platform_administrator', NULL,
            'quota.overrides_changed', 'tenant_resource_quota', p_tenant_id, 'success',
            p_correlation_id, jsonb_build_object('override_keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(p_overrides) AS k)),
            clock_timestamp()
          );
          RETURN QUERY
            SELECT q.tenant_id, q.limits, q.overrides
            FROM public.tenant_resource_quotas AS q WHERE q.tenant_id = p_tenant_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.platform_recent_audit(p_limit integer)
        RETURNS TABLE(
          id uuid, tenant_id uuid, actor_type text, action_type text,
          resource_type text, outcome text, occurred_at timestamptz
        )
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $$
          SELECT a.id, a.tenant_id, a.actor_type::text, a.action_type::text,
                 a.resource_type::text, a.outcome::text, a.occurred_at
          FROM public.audit_logs AS a
          ORDER BY a.occurred_at DESC
          LIMIT LEAST(GREATEST(p_limit, 1), 500)
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.platform_recent_security_events(p_limit integer)
        RETURNS TABLE(
          id uuid, tenant_id uuid, event_type text, severity text,
          sanitized_detail jsonb, occurred_at timestamptz
        )
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $$
          SELECT e.id, e.tenant_id, e.event_type::text, e.severity::text,
                 e.sanitized_detail, e.occurred_at
          FROM public.security_events AS e
          ORDER BY e.occurred_at DESC
          LIMIT LEAST(GREATEST(p_limit, 1), 500)
        $$
        """
    )
    for signature in PLATFORM_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO graphrec_app")


def downgrade() -> None:
    for signature in PLATFORM_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
    for table in DOMAIN_TABLES:
        for operation in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_{operation} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_column("training_jobs", "dataset_snapshot_id")
