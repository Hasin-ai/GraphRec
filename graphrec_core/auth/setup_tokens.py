"""One-time account setup tokens.

A token is 32 random bytes (URL-safe base64). Only its SHA-256 hash is stored,
so a database read does not reveal usable tokens. Tokens expire, are consumed
on first use, and issuing a new token revokes any older unused ones.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from graphrec_core.database.models import AccountSetupToken

TOKEN_BYTES = 32


def setup_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def revoke_open_setup_tokens(
    session: Session, *, tenant_id: UUID, user_id: UUID, now: datetime
) -> int:
    """Revoke every unused, unrevoked token of one user. Requires the tenant context."""

    result = session.execute(
        update(AccountSetupToken)
        .where(
            AccountSetupToken.tenant_id == tenant_id,
            AccountSetupToken.user_id == user_id,
            AccountSetupToken.used_at.is_(None),
            AccountSetupToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return int(result.rowcount or 0)


def issue_setup_token(
    session: Session, *, tenant_id: UUID, user_id: UUID, ttl_seconds: int, now: datetime
) -> tuple[str, datetime]:
    """Stage a new token for ``user_id`` and return ``(token, expires_at)``.

    Requires the tenant context (``set_local_tenant``) in the current transaction;
    the caller commits.
    """

    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = now + timedelta(seconds=ttl_seconds)
    session.add(
        AccountSetupToken(
            id=uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            token_hash=setup_token_hash(token),
            created_at=now,
            expires_at=expires_at,
            used_at=None,
            revoked_at=None,
        )
    )
    return token, expires_at
