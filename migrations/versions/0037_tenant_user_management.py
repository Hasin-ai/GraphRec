"""UC-27-adjacent per-user management: tenant administrators may change a
member's role. Status, credential and epoch updates were already granted."""

from alembic import op

revision = "0037_tenant_user_management"
down_revision = "0036_platform_operators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT UPDATE (role, display_name) ON tenant_users TO graphrec_app")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (role, display_name) ON tenant_users FROM graphrec_app")
