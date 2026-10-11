"""A-17: registration_requests is tenant-scoped like every other tenant table.

The runtime role could SELECT every tenant's stored registration response
(tenant name and administrator email). It now reads and writes rows only
inside its own tenant context (forced RLS), and answers the two
pre-tenant questions registration needs through SECURITY DEFINER lookups.
"""

from alembic import op

revision = "0033_registration_requests_rls"
down_revision = "0032_refresh_rotation"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
COLUMNS = "tenant_id uuid, request_hash text, response_body jsonb"


def upgrade() -> None:
    op.execute("ALTER TABLE registration_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE registration_requests FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY registration_requests_insert ON registration_requests FOR INSERT TO graphrec_app WITH CHECK ({TENANT})")
    op.execute(f"CREATE POLICY registration_requests_select ON registration_requests FOR SELECT TO graphrec_app USING ({TENANT})")
    for name, column in (("registration_by_idempotency_key", "idempotency_key_hash"),
                         ("registration_by_request_hash", "request_hash")):
        op.execute(f"""
          CREATE FUNCTION public.{name}(p_hash text)
          RETURNS TABLE({COLUMNS})
          LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $function$
            SELECT r.tenant_id, r.request_hash::text, r.response_body::jsonb
            FROM public.registration_requests r WHERE r.{column} = p_hash LIMIT 1
          $function$
        """)
        op.execute(f"REVOKE ALL ON FUNCTION public.{name}(text) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{name}(text) TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.registration_by_request_hash(text)")
    op.execute("DROP FUNCTION public.registration_by_idempotency_key(text)")
    op.execute("DROP POLICY registration_requests_select ON registration_requests")
    op.execute("DROP POLICY registration_requests_insert ON registration_requests")
    op.execute("ALTER TABLE registration_requests NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE registration_requests DISABLE ROW LEVEL SECURITY")
