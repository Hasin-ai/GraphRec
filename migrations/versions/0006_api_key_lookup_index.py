"""index predecessor API-key verifier lookup

Revision ID: 0006_api_key_lookup_index
Revises: 0005_api_key_lifecycle
Create Date: 2026-08-01
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "0006_api_key_lookup_index"
down_revision: Union[str, None] = "0005_api_key_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_api_keys_previous_hash", "api_keys", ["previous_key_hash"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_previous_hash", table_name="api_keys")
