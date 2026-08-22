"""API credentials.

`key_hash` is an HMAC digest and never leaves the database — there is no
response model anywhere that carries it, and the structural test in
`tests/isolation/test_model_schema_parity.py` fails if one appears.

The lifecycle predicates live here rather than in the service because the
console derives them client-side (dc.html L1107) and a real client must not:
`state` depends on the comparison between `expires_at` and *server* time, and a
client that computes it from its own clock will show a usable credential as
expired the moment the two disagree.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from graphrec.common.enums import CredentialScope, CredentialState
from graphrec.db.models.base import Base, TenantOwned, pk_uuid, utcnow_column


class ApiKey(Base, TenantOwned):
    """A credential a tenant's application authenticates with.

    Rotation happens in place on the same `key_id`, matching the console's
    rotate dialog, which mutates the row it was opened on (dc.html L1150). The
    `previous_*` quartet holds the outgoing credential for the duration of a
    grace window and is cleared once it lapses.
    """

    __tablename__ = "api_keys"

    key_id: Mapped[uuid.UUID] = pk_uuid()
    name: Mapped[str] = mapped_column(Text)
    visible_prefix: Mapped[str] = mapped_column(Text, unique=True)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary)
    hash_version: Mapped[int] = mapped_column(Integer)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))

    previous_visible_prefix: Mapped[str | None] = mapped_column(Text)
    previous_key_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    previous_hash_version: Mapped[int | None] = mapped_column(Integer)
    previous_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[dt.datetime] = utcnow_column()
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenant_users.tenant_user_id", ondelete="SET NULL")
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rotation_reason: Mapped[str | None] = mapped_column(Text)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    def state(self, *, now: dt.datetime) -> CredentialState:
        """`revoked` beats `expired` beats `usable`.

        The precedence is the prototype's, at dc.html L1107:
        `c.revoked ? 'revoked' : (c.expires < today ? 'expired' : 'usable')`.
        It matters that revocation wins: a credential revoked before its expiry
        must not later read as merely expired, because "expired" invites
        rotation and this one must not be rotated.
        """
        if self.revoked_at is not None:
            return CredentialState.REVOKED
        if self.expires_at <= now:
            return CredentialState.EXPIRED
        return CredentialState.USABLE

    def is_usable(self, *, now: dt.datetime) -> bool:
        return self.state(now=now) is CredentialState.USABLE

    def granted_scopes(self) -> frozenset[CredentialScope]:
        """The stored scopes, as enum members.

        Unknown strings are dropped rather than raising. A scope removed from
        the vocabulary in a later release must not make an existing credential
        unusable for the scopes it still legitimately holds — and it must
        certainly not grant anything, which dropping guarantees.
        """
        known = {scope.value for scope in CredentialScope}
        return frozenset(CredentialScope(value) for value in self.scopes if value in known)

    def grace_is_open(self, *, now: dt.datetime) -> bool:
        return self.previous_expires_at is not None and self.previous_expires_at > now


__all__ = ["ApiKey"]
