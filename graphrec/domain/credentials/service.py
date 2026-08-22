"""Credential lifecycle and the verification path.

The lifecycle side (create, rotate, revoke, list) runs inside a tenant-bound
session and is unremarkable. The verification side is the one to read carefully,
because it runs *before* any tenant context exists — a credential is how the
caller proves which tenant they are, so nothing can be bound until it has been
checked.

That makes `verify` structurally the same problem as sign-in, and it gets the
same answer: the credential resolves to a tenant through a narrow lookup that
returns one identifier and nothing else, the context is bound to that
identifier, and only then is any tenant-owned row read. The tenant is never
taken from a header, a path or a body. See ADR 0008 for the general pattern and
ADR 0010 for the rotation grace window.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.auth import api_keys as secrets_lib
from graphrec.common.enums import CredentialScope, CredentialState
from graphrec.common.errors import AuthError, ConflictError, LimitError, ValidationError
from graphrec.db.models import ApiKey
from graphrec.db.tenant_context import bind_tenant

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

#: The expiry choices the console offers (dc.html L1134). Not a free integer:
#: the create dialog is a select, and accepting arbitrary values would mean the
#: API and the console disagree about what a valid credential looks like.
ALLOWED_EXPIRY_DAYS = (90, 180, 365)


@dataclasses.dataclass(frozen=True, slots=True)
class IssuedCredential:
    """A credential and its secret, at one of the two moments the secret exists."""

    api_key: ApiKey
    secret: str

    def __repr__(self) -> str:
        return f"IssuedCredential(key_id={self.api_key.key_id!r}, secret=<redacted>)"


@dataclasses.dataclass(frozen=True, slots=True)
class VerifiedCredential:
    """The outcome of authenticating a presented credential."""

    api_key: ApiKey
    tenant_id: uuid.UUID
    scopes: frozenset[CredentialScope]
    #: True when the caller authenticated with the outgoing secret of a rotation
    #: still inside its grace window. Surfaced so the response can carry a
    #: deprecation signal and the audit trail can record it, rather than a
    #: silent success that tells an integrator nothing until the window closes.
    used_grace_secret: bool


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class CredentialService:
    """Issues, rotates, revokes and verifies API credentials."""

    def __init__(
        self,
        *,
        pepper: str,
        hash_version: int,
        max_active_per_tenant: int = 25,
        max_scopes: int = 12,
        max_name_length: int = 100,
        max_grace_seconds: int = 86_400,
    ) -> None:
        self._pepper = pepper
        self._hash_version = hash_version
        self._max_active = max_active_per_tenant
        self._max_scopes = max_scopes
        self._max_name_length = max_name_length
        self._max_grace_seconds = max_grace_seconds

    # ------------------------------------------------------------- lifecycle

    def _validate(self, *, name: str, scopes: list[str], expires_in_days: int) -> None:
        """Refuse with the prototype's wording, in the prototype's order.

        The console checks the name first and the scopes second (dc.html
        L1136-1137), so a request missing both gets the name error. Matching
        that matters: the console highlights the field named in the response,
        and a mismatch would highlight the wrong one.
        """
        if not name.strip():
            raise ValidationError("credential_name_required").with_field(
                "name", "Give the credential a name so it can be told apart in this list."
            )
        if len(name) > self._max_name_length:
            raise ValidationError("credential_name_required").with_field(
                "name", "Give the credential a name so it can be told apart in this list."
            )
        if not scopes:
            raise ValidationError("credential_requires_scope").with_field(
                "scopes",
                "Select at least one integration operation. "
                "A credential with no scope cannot authorize anything.",
            )
        if len(scopes) > self._max_scopes:
            raise ValidationError("credential_requires_scope").with_field("scopes", "Too many.")
        known = {scope.value for scope in CredentialScope}
        unknown = [value for value in scopes if value not in known]
        if unknown:
            # Never echo what was sent. An unrecognised scope string is caller
            # input, and reflecting it back is how a payload reaches a log or a
            # console that renders it.
            raise ValidationError("credential_requires_scope").with_field(
                "scopes", "One or more selected operations are not recognized."
            )
        if expires_in_days not in ALLOWED_EXPIRY_DAYS:
            raise ValidationError("credential_requires_scope").with_field(
                "expires_in_days", "Choose one of the offered expiry periods."
            )

    async def _active_count(self, session: AsyncSession, *, now: dt.datetime) -> int:
        """Credentials that are neither revoked nor expired.

        Scoped by RLS to the bound tenant, so there is no `tenant_id` predicate
        here and there must not be one: adding it would imply the policy is not
        trusted, and the day someone removes it the query still looks right.
        """
        result = await session.scalar(
            sa.select(sa.func.count())
            .select_from(ApiKey)
            .where(ApiKey.revoked_at.is_(None), ApiKey.expires_at > now)
        )
        return int(result or 0)

    async def create(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        created_by: uuid.UUID | None,
        name: str,
        scopes: list[str],
        expires_in_days: int,
    ) -> IssuedCredential:
        now = _utcnow()
        self._validate(name=name, scopes=scopes, expires_in_days=expires_in_days)

        used = await self._active_count(session, now=now)
        if used >= self._max_active:
            # The counts go in the message because the console renders them
            # (`{used} of {limit}`), and a cap error without them tells an
            # administrator to go and count rows by hand.
            raise LimitError(
                "credential_cap_reached",
                copy_args={"used": used, "limit": self._max_active},
            )

        generated = secrets_lib.issue(pepper=self._pepper, hash_version=self._hash_version)
        api_key = ApiKey(
            tenant_id=tenant_id,
            name=name.strip(),
            visible_prefix=generated.visible_prefix,
            key_hash=generated.digest,
            hash_version=generated.hash_version,
            scopes=list(scopes),
            created_by=created_by,
            expires_at=now + dt.timedelta(days=expires_in_days),
        )
        session.add(api_key)
        await session.flush()
        return IssuedCredential(api_key=api_key, secret=generated.secret)

    async def rotate(
        self,
        session: AsyncSession,
        *,
        key_id: uuid.UUID,
        scopes: list[str] | None,
        grace_seconds: int,
        reason: str | None,
    ) -> IssuedCredential:
        """Issue a new secret on the same credential.

        In place, on the same `key_id`, because the console's rotate dialog
        mutates the row it was opened on (dc.html L1150) — the credential keeps
        its identity, its name and its place in the list, and only the secret
        and prefix change.

        `grace_seconds` defaults to zero at the route, which reproduces the
        dialog's promise that "requests still using the old secret will fail
        authentication" (L1145). A caller who asks for a window gets one, capped
        at `MAX_API_KEY_GRACE_SECONDS`. ADR 0010.
        """
        now = _utcnow()
        api_key = await self._load_for_update(session, key_id=key_id)

        if api_key.revoked_at is not None:
            raise ConflictError("credential_revoked")
        if grace_seconds < 0 or grace_seconds > self._max_grace_seconds:
            raise ValidationError("credential_requires_scope").with_field(
                "grace_seconds", "Grace period is outside the permitted range."
            )

        next_scopes = api_key.scopes if scopes is None else scopes
        self._validate(name=api_key.name, scopes=list(next_scopes), expires_in_days=90)

        generated = secrets_lib.issue(pepper=self._pepper, hash_version=self._hash_version)

        if grace_seconds > 0:
            api_key.previous_visible_prefix = api_key.visible_prefix
            api_key.previous_key_hash = api_key.key_hash
            api_key.previous_hash_version = api_key.hash_version
            api_key.previous_expires_at = now + dt.timedelta(seconds=grace_seconds)
        else:
            # Explicit, not left over. A second rotation inside an open window
            # must not silently extend the first one's grace.
            api_key.previous_visible_prefix = None
            api_key.previous_key_hash = None
            api_key.previous_hash_version = None
            api_key.previous_expires_at = None

        api_key.visible_prefix = generated.visible_prefix
        api_key.key_hash = generated.digest
        api_key.hash_version = generated.hash_version
        api_key.scopes = list(next_scopes)
        api_key.rotated_at = now
        api_key.rotation_reason = reason
        await session.flush()
        return IssuedCredential(api_key=api_key, secret=generated.secret)

    async def revoke(self, session: AsyncSession, *, key_id: uuid.UUID) -> ApiKey:
        """Immediate and irreversible (dc.html L1157). Repeating it is safe.

        A second revoke is not an error: the caller's intent is already
        satisfied, and reporting a conflict would make a retry after a dropped
        response look like a failure.
        """
        api_key = await self._load_for_update(session, key_id=key_id)
        if api_key.revoked_at is None:
            api_key.revoked_at = _utcnow()
            # An open grace window dies with the credential. Leaving it would
            # mean a revoked credential still authenticated, which is precisely
            # what the console promises it does not.
            api_key.previous_visible_prefix = None
            api_key.previous_key_hash = None
            api_key.previous_hash_version = None
            api_key.previous_expires_at = None
            await session.flush()
        return api_key

    async def _load_for_update(self, session: AsyncSession, *, key_id: uuid.UUID) -> ApiKey:
        """Load one credential in the bound tenant, or refuse as absent.

        Gate 4: a credential belonging to another tenant is invisible to the
        policy, so this raises the same `not_found` as an identifier that names
        nothing at all. There is no branch here that could tell them apart,
        which is the point — a 403 would confirm the credential exists.
        """
        api_key = await session.scalar(
            sa.select(ApiKey).where(ApiKey.key_id == key_id).with_for_update()
        )
        if api_key is None:
            from graphrec.common.errors import NotFoundError

            raise NotFoundError("not_found")
        return api_key

    async def list_for_tenant(
        self, session: AsyncSession, *, state: CredentialState | None = None
    ) -> list[ApiKey]:
        rows = list(
            (
                await session.scalars(
                    sa.select(ApiKey).order_by(ApiKey.created_at.desc(), ApiKey.key_id)
                )
            ).all()
        )
        if state is None:
            return rows
        now = _utcnow()
        return [row for row in rows if row.state(now=now) is state]

    async def get(self, session: AsyncSession, *, key_id: uuid.UUID) -> ApiKey:
        api_key = await session.scalar(sa.select(ApiKey).where(ApiKey.key_id == key_id))
        if api_key is None:
            from graphrec.common.errors import NotFoundError

            raise NotFoundError("not_found")
        return api_key

    # ---------------------------------------------------------- verification

    async def verify(self, session: AsyncSession, *, presented: str) -> VerifiedCredential:
        """Authenticate a presented credential and bind the session to its tenant.

        Runs before any tenant context exists, so it uses the same narrow
        resolver pattern sign-in uses: resolve a prefix to one identifier
        through a `SECURITY DEFINER` function that returns nothing else, bind,
        then read. Every refusal is the same `invalid_credentials`, because
        distinguishing "no such prefix" from "wrong secret" from "revoked"
        hands an attacker a classifier for free.
        """
        prefix = secrets_lib.split_presented(presented)
        if prefix is None:
            secrets_lib.dummy_verify(presented, pepper=self._pepper)
            raise AuthError("invalid_credentials")

        resolved = await session.scalar(
            sa.select(sa.func.tenant_lookup.resolve_api_key_prefix(prefix))
        )
        if resolved is None:
            secrets_lib.dummy_verify(presented, pepper=self._pepper)
            raise AuthError("invalid_credentials")

        await bind_tenant(session, resolved)
        api_key = await session.scalar(
            sa.select(ApiKey).where(
                sa.or_(
                    ApiKey.visible_prefix == prefix,
                    ApiKey.previous_visible_prefix == prefix,
                )
            )
        )
        if api_key is None:
            secrets_lib.dummy_verify(presented, pepper=self._pepper)
            raise AuthError("invalid_credentials")

        now = _utcnow()
        used_grace = False

        if api_key.visible_prefix == prefix:
            matched = secrets_lib.verify(
                presented,
                digest=api_key.key_hash,
                pepper=self._pepper,
                hash_version=api_key.hash_version,
            )
        elif (
            api_key.previous_key_hash is not None
            and api_key.previous_hash_version is not None
            and api_key.grace_is_open(now=now)
        ):
            matched = secrets_lib.verify(
                presented,
                digest=api_key.previous_key_hash,
                pepper=self._pepper,
                hash_version=api_key.previous_hash_version,
            )
            used_grace = matched
        else:
            # A lapsed grace prefix still resolves — the row is still there —
            # but it verifies against nothing. Burn the work anyway.
            secrets_lib.dummy_verify(presented, pepper=self._pepper)
            matched = False

        if not matched:
            raise AuthError("invalid_credentials")

        # State is checked after the secret, not before. Checking first would
        # let a caller learn that a prefix names a revoked credential without
        # holding the secret for it.
        if not api_key.is_usable(now=now):
            raise AuthError("invalid_credentials")

        api_key.last_used_at = now
        return VerifiedCredential(
            api_key=api_key,
            tenant_id=api_key.tenant_id,
            scopes=api_key.granted_scopes(),
            used_grace_secret=used_grace,
        )


__all__ = ["ALLOWED_EXPIRY_DAYS", "CredentialService", "IssuedCredential", "VerifiedCredential"]
