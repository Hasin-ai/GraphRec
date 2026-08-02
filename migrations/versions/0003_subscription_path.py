"""tenant-protected subscription reads

Revision ID: 0003_subscription_path
Revises: 0002_tenant_login
Create Date: 2026-08-01
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "0003_subscription_path"
down_revision: Union[str, None] = "0002_tenant_login"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenants_tenant_select ON tenants
        FOR SELECT TO graphrec_app
        USING (
          id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY tenants_tenant_insert ON tenants
        FOR INSERT TO graphrec_app
        WITH CHECK (
          id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
        )
        """
    )
    op.execute("GRANT SELECT ON tenants TO graphrec_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON tenants FROM graphrec_app")
    op.execute("DROP POLICY IF EXISTS tenants_tenant_insert ON tenants")
    op.execute("DROP POLICY IF EXISTS tenants_tenant_select ON tenants")
    op.execute("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")
