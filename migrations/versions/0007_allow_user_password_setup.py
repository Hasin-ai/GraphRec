"""allow password setup updates on tenant_users table

Revision ID: 0007_allow_user_password_setup
Revises: 0006_api_key_lookup_index
Create Date: 2026-08-01
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "0007_allow_user_password_setup"
down_revision: Union[str, None] = "0006_api_key_lookup_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "GRANT UPDATE (credential_digest, status, last_authenticated_at) ON tenant_users TO graphrec_app"
    )


def downgrade() -> None:
    op.execute("REVOKE UPDATE (credential_digest, status) ON tenant_users FROM graphrec_app")
