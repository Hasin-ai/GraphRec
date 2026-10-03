"""One-time, operator-issued password recovery and access-token invalidation."""

from alembic import op

revision = "0021_account_recovery"
down_revision = "0020_platform_plan_edit"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_users ADD COLUMN auth_epoch integer NOT NULL DEFAULT 0")
    op.execute("GRANT UPDATE (auth_epoch) ON tenant_users TO graphrec_app")
    op.execute(f"CREATE POLICY refresh_sessions_tenant_update ON refresh_sessions FOR UPDATE TO graphrec_app USING ({TENANT}) WITH CHECK ({TENANT})")
    op.execute("GRANT UPDATE (revoked_at) ON refresh_sessions TO graphrec_app")
    op.execute("""
      CREATE TABLE account_recovery_tokens (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id uuid NOT NULL,
        token_hash varchar(64) NOT NULL UNIQUE,
        created_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        revoked_at timestamptz,
        CONSTRAINT fk_account_recovery_tokens_user FOREIGN KEY (tenant_id, user_id)
          REFERENCES tenant_users(tenant_id, id) ON DELETE CASCADE,
        CONSTRAINT ck_account_recovery_tokens_expiry CHECK (expires_at > created_at)
      )
    """)
    op.execute("CREATE INDEX ix_account_recovery_tokens_user ON account_recovery_tokens(tenant_id, user_id)")
    op.execute("ALTER TABLE account_recovery_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE account_recovery_tokens FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY account_recovery_tokens_select ON account_recovery_tokens FOR SELECT TO graphrec_app USING ({TENANT})")
    op.execute(f"CREATE POLICY account_recovery_tokens_insert ON account_recovery_tokens FOR INSERT TO graphrec_app WITH CHECK ({TENANT})")
    op.execute(f"CREATE POLICY account_recovery_tokens_update ON account_recovery_tokens FOR UPDATE TO graphrec_app USING ({TENANT}) WITH CHECK ({TENANT})")
    op.execute("GRANT SELECT, INSERT ON account_recovery_tokens TO graphrec_app")
    op.execute("GRANT UPDATE (used_at, revoked_at) ON account_recovery_tokens TO graphrec_app")
    op.execute("""
      CREATE FUNCTION public.resolve_account_recovery_token(p_token_hash text)
      RETURNS TABLE(token_id uuid, tenant_id uuid, user_id uuid, normalized_email text,
        user_status text, user_role text, tenant_status text, expires_at timestamptz,
        used_at timestamptz, revoked_at timestamptz)
      LANGUAGE sql SECURITY DEFINER STABLE SET search_path = pg_catalog, public AS $function$
        SELECT rt.id, rt.tenant_id, rt.user_id, lower(tu.email::text), tu.status::text,
          tu.role::text, t.status::text, rt.expires_at, rt.used_at, rt.revoked_at
        FROM public.account_recovery_tokens rt
        JOIN public.tenant_users tu ON tu.tenant_id = rt.tenant_id AND tu.id = rt.user_id
        JOIN public.tenants t ON t.id = rt.tenant_id
        WHERE rt.token_hash = p_token_hash
      $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.resolve_account_recovery_token(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.resolve_account_recovery_token(text) TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.resolve_account_recovery_token(text)")
    op.execute("DROP TABLE account_recovery_tokens")
    op.execute("REVOKE UPDATE (revoked_at) ON refresh_sessions FROM graphrec_app")
    op.execute("DROP POLICY refresh_sessions_tenant_update ON refresh_sessions")
    op.execute("REVOKE UPDATE (auth_epoch) ON tenant_users FROM graphrec_app")
    op.execute("ALTER TABLE tenant_users DROP COLUMN auth_epoch")
