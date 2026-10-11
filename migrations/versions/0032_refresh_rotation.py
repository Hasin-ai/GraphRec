"""A-05: refresh-token rotation with reuse detection.

``resolve_refresh_session`` lets the unauthenticated refresh endpoint find the
session for a presented token hash (tenant context is not known yet). It
returns whether the session has already been rotated, so a replayed (stolen)
token can revoke the whole session family.
"""

from alembic import op

revision = "0032_refresh_rotation"
down_revision = "0031_free_plan_serving_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_refresh_sessions_rotated_from ON refresh_sessions(rotated_from_id)")
    op.execute("""
      CREATE FUNCTION public.resolve_refresh_session(p_token_hash text)
      RETURNS TABLE(session_id uuid, tenant_id uuid, user_id uuid, normalized_email text,
        user_status text, user_role text, tenant_status text, expires_at timestamptz,
        revoked_at timestamptz, rotated boolean)
      LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $function$
        SELECT rs.id, rs.tenant_id, rs.user_id, lower(tu.email::text), tu.status::text,
          tu.role::text, t.status::text, rs.expires_at, rs.revoked_at,
          EXISTS (SELECT 1 FROM public.refresh_sessions child WHERE child.rotated_from_id = rs.id)
        FROM public.refresh_sessions rs
        JOIN public.tenant_users tu ON tu.tenant_id = rs.tenant_id AND tu.id = rs.user_id
        JOIN public.tenants t ON t.id = rs.tenant_id
        WHERE rs.token_hash = p_token_hash
      $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.resolve_refresh_session(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.resolve_refresh_session(text) TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.resolve_refresh_session(text)")
    op.execute("DROP INDEX IF EXISTS ix_refresh_sessions_rotated_from")
