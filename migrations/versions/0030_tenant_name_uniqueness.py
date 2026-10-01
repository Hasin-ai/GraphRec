"""D10: case-insensitive tenant-name check for registration.

The runtime role cannot read ``tenants``, so registration asks this SECURITY
DEFINER function. A unique index is not added because existing deployments may
already hold duplicate names (it would fail to build); the function check is
enforced for every new registration.
"""

from alembic import op

revision = "0030_tenant_name_uniqueness"
down_revision = "0029_serving_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE FUNCTION public.tenant_name_in_use(p_name text) RETURNS boolean
      LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $function$
        SELECT EXISTS (SELECT 1 FROM public.tenants
                       WHERE lower(btrim(name)) = lower(btrim(p_name)))
      $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.tenant_name_in_use(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.tenant_name_in_use(text) TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.tenant_name_in_use(text)")
