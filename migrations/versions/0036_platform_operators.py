"""D-04 (approved 2026-10-08): named platform operators with roles.

Operators are platform staff, not tenant data, so the table is not under tenant
RLS. The runtime role reads it for sign-in and writes only the columns operator
management needs; there is no DELETE grant (operators are disabled, never
removed, so audit attribution keeps resolving).
"""

from alembic import op

revision = "0036_platform_operators"
down_revision = "0035_plan_limit_semantics"
branch_labels = None
depends_on = None

ROLES = ("platform", "plan_management", "monitoring", "audit", "operator_admin")


def upgrade() -> None:
    roles = ", ".join(f"'{r}'" for r in ROLES)
    op.execute(f"""
      CREATE TABLE platform_operators (
        id uuid PRIMARY KEY,
        email citext NOT NULL UNIQUE,
        display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 100),
        password_hash text NOT NULL,
        roles text[] NOT NULL CHECK (roles <@ ARRAY[{roles}]::text[] AND cardinality(roles) >= 1),
        status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
        auth_epoch integer NOT NULL DEFAULT 0,
        created_at timestamptz NOT NULL DEFAULT now(),
        created_by uuid REFERENCES platform_operators(id),
        last_login_at timestamptz
      )
    """)
    op.execute("GRANT SELECT, INSERT ON platform_operators TO graphrec_app")
    op.execute("GRANT UPDATE (display_name, password_hash, roles, status, auth_epoch, last_login_at) "
               "ON platform_operators TO graphrec_app")


def downgrade() -> None:
    op.execute("DROP TABLE platform_operators")
