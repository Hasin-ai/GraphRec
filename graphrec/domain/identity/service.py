"""Identity operations, kept out of the routers.

The router's job is HTTP; this module's job is what the operation means. The
separation earns its keep in two places in particular — sign-in, where the
sequence of checks is a security property rather than a style, and the
last-active-administrator rule, which needs a row lock to be correct at all.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from graphrec.auth.passwords import hash_password, needs_rehash, verify_password
from graphrec.auth.tokens import Realm, TokenService, TokenType, digest_token
from graphrec.common.clock import utcnow
from graphrec.common.enums import TenantRole, TenantStatus, UserStatus
from graphrec.common.errors import AuthError, ConflictError, NotFoundError, ValidationError
from graphrec.common.ids import new_token, uuid7
from graphrec.db.models import Invitation, PlatformUser, RefreshSession, Tenant, TenantUser
from graphrec.db.tenant_context import bind_tenant

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


#: Prefix from the prototype's placeholder (dc.html L1045: `inv_…`). It is
#: cosmetic to the database — the digest is of the whole string — and useful to
#: a human triaging a support ticket, who can tell an invitation from a recovery
#: proof (`rec_…`) without knowing either secret.
INVITATION_TOKEN_PREFIX = "inv_"


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    """A newly invited user and the one-time token that activates the account.

    The token is in this object and in the response, and nowhere else. What the
    database holds is its SHA-256 digest, so a dump of `invitations` does not
    let the reader accept anybody's invitation.
    """

    user: TenantUser
    invitation: Invitation
    token: str


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """What a successful sign-in hands back. The refresh token is shown once."""

    access_token: str
    access_expires_at: dt.datetime
    refresh_token: str
    refresh_expires_at: dt.datetime


class IdentityService:
    def __init__(self, tokens: TokenService, *, invitation_ttl_seconds: int = 604_800) -> None:
        self._tokens = tokens
        self._invitation_ttl = dt.timedelta(seconds=invitation_ttl_seconds)

    # ------------------------------------------------------- registration

    async def register_tenant(
        self,
        session: AsyncSession,
        *,
        tenant_name: str,
        tenant_code: str,
        email: str,
        password: str,
        plan_id: uuid.UUID | None,
    ) -> tuple[Tenant, TenantUser]:
        """Create a tenant and its first administrator, in one transaction.

        The identifier is minted here and the database context is bound to it
        *before* the insert. That ordering is what makes the `INSERT` grant on
        `tenants` safe: the `WITH CHECK` clause passes only for the row whose
        identifier we just bound, so this path can create the tenant it is about
        to own and no other.

        The tenant is created `pending`, not `active`. SRS §5.2.1 makes
        activation a platform decision, and the prototype's own account screen is
        built around a tenant that exists but cannot yet act.
        """
        tenant_id = uuid7()
        await bind_tenant(session, tenant_id)

        existing = await session.scalar(
            select(func.count()).select_from(Tenant).where(Tenant.tenant_name == tenant_name)
        )
        if existing:
            # Reachable only for a name this caller can see — which, under RLS,
            # is none. The real guard is the unique index; this branch turns the
            # integrity error into the approved sentence when it does fire.
            raise ConflictError(
                "tenant_name_already_registered", copy_args={"business_name": tenant_name}
            ).with_field("tenant_name", "Business name already registered.")

        tenant = Tenant(
            tenant_id=tenant_id,
            tenant_code=tenant_code,
            tenant_name=tenant_name,
            plan_id=plan_id,
            status=TenantStatus.PENDING.value,
            settings={},
        )
        session.add(tenant)
        await session.flush()

        administrator = TenantUser(
            tenant_user_id=uuid7(),
            tenant_id=tenant_id,
            email=email.strip().lower(),
            display_name=email.split("@", 1)[0],
            credential_digest=hash_password(password),
            role=TenantRole.TENANT_ADMINISTRATOR.value,
            # Active: this account is created by the person holding the password,
            # so there is nothing to confirm out of band. `invited` is for users
            # someone else creates.
            status=UserStatus.ACTIVE.value,
        )
        session.add(administrator)
        await session.flush()
        return tenant, administrator

    # ------------------------------------------------------------ sign-in

    async def authenticate_tenant_user(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        email: str,
        password: str,
    ) -> tuple[Tenant, TenantUser]:
        """Verify a tenant member's credentials. One failure message throughout.

        Every refusal below raises the same `invalid_credentials` — unknown
        tenant, unknown email, wrong password, invited, locked, disabled. The
        prototype is explicit about why (dc.html L1572): "The credentials
        supplied are not valid, or the account cannot sign in." Naming which of
        those it was would let anyone enumerate a tenant's staff.

        Note the password is verified even when no user matched. `verify_password`
        hashes against a dummy digest in that case, so a miss costs the same as a
        hit and the timing does not answer the question the message refuses to.
        """
        await bind_tenant(session, tenant_id)

        tenant = await session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        user = await session.scalar(
            select(TenantUser).where(TenantUser.email == email.strip().lower())
        )

        password_ok = verify_password(user.credential_digest if user else None, password)

        if tenant is None or user is None or not password_ok or not user.can_authenticate:
            raise AuthError("invalid_credentials")

        now = utcnow()
        user.last_authenticated_at = now
        user.failed_attempts = 0
        if needs_rehash(user.credential_digest):
            # The only moment the plaintext is in hand. Upgrading here avoids
            # ever needing a mass reset when the parameters are raised.
            user.credential_digest = hash_password(password)
        return tenant, user

    async def authenticate_platform_user(
        self, session: AsyncSession, *, email: str, password: str
    ) -> PlatformUser:
        """The operator equivalent. Same shape, same single message."""
        user = await session.scalar(
            select(PlatformUser).where(PlatformUser.email == email.strip().lower())
        )
        password_ok = verify_password(user.credential_digest if user else None, password)
        if user is None or not password_ok or not user.can_authenticate:
            raise AuthError("invalid_platform_credentials")

        user.last_authenticated_at = utcnow()
        user.failed_attempts = 0
        return user

    # ----------------------------------------------------------- sessions

    async def issue_tenant_session(
        self,
        session: AsyncSession,
        *,
        tenant: Tenant,
        user: TenantUser,
        user_agent: str | None,
        client_address: str | None,
    ) -> IssuedSession:
        access, access_expiry = self._tokens.issue_tenant_access(
            tenant_id=tenant.tenant_id, user_id=user.tenant_user_id, role=user.role
        )
        refresh = self._tokens.issue_session_token(
            token_type=TokenType.REFRESH,
            realm=Realm.TENANT,
            user_id=user.tenant_user_id,
            tenant_id=tenant.tenant_id,
        )
        session.add(
            RefreshSession(
                refresh_session_id=refresh.session_id,
                tenant_user_id=user.tenant_user_id,
                tenant_id=tenant.tenant_id,
                # The digest, never the token. A database dump yields nothing
                # that can be replayed.
                token_digest=refresh.digest,
                expires_at=refresh.expires_at,
                user_agent=user_agent,
                client_address=client_address,
            )
        )
        await session.flush()
        return IssuedSession(
            access_token=access,
            access_expires_at=access_expiry,
            refresh_token=refresh.token,
            refresh_expires_at=refresh.expires_at,
        )

    async def issue_platform_session(
        self,
        session: AsyncSession,
        *,
        user: PlatformUser,
        user_agent: str | None,
        client_address: str | None,
    ) -> IssuedSession:
        access, access_expiry = self._tokens.issue_platform_access(
            user_id=user.platform_user_id, permissions=user.granted()
        )
        refresh = self._tokens.issue_session_token(
            token_type=TokenType.REFRESH,
            realm=Realm.PLATFORM,
            user_id=user.platform_user_id,
            tenant_id=None,
        )
        session.add(
            RefreshSession(
                refresh_session_id=refresh.session_id,
                platform_user_id=user.platform_user_id,
                tenant_id=None,
                token_digest=refresh.digest,
                expires_at=refresh.expires_at,
                user_agent=user_agent,
                client_address=client_address,
            )
        )
        await session.flush()
        return IssuedSession(
            access_token=access,
            access_expires_at=access_expiry,
            refresh_token=refresh.token,
            refresh_expires_at=refresh.expires_at,
        )

    async def rotate_tenant_session(
        self,
        session: AsyncSession,
        *,
        refresh_token: str,
        user_agent: str | None,
        client_address: str | None,
    ) -> IssuedSession:
        """Exchange a refresh token, revoking the one presented.

        Rotation is unconditional: the presented token is revoked whether or not
        it was already used. A replayed token therefore fails, and — because
        `superseded_by` records the chain — a replay is visible afterwards rather
        than merely refused.
        """
        realm, user_id, session_id, tenant_id = self._tokens.verify_session_token(
            refresh_token, token_type=TokenType.REFRESH
        )
        if realm is not Realm.TENANT or tenant_id is None:
            raise AuthError("invalid_credentials")

        # The context comes from the verified `tid` claim, before any row is
        # read. This is the reason refresh tokens are signed rather than opaque:
        # an opaque string would force a lookup with no tenant bound.
        await bind_tenant(session, tenant_id)

        stored = await session.scalar(
            select(RefreshSession)
            .where(RefreshSession.refresh_session_id == session_id)
            .with_for_update()
        )
        now = utcnow()
        if (
            stored is None
            or stored.token_digest != digest_token(refresh_token)
            or stored.tenant_user_id != user_id
            or not stored.is_usable(now)
        ):
            raise AuthError("invalid_credentials")

        tenant = await session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        user = await session.scalar(select(TenantUser).where(TenantUser.tenant_user_id == user_id))
        if tenant is None or user is None or not user.can_authenticate:
            raise AuthError("invalid_credentials")
        if not tenant.is_operable:
            # Refreshing must not resurrect access to a suspended tenant.
            raise AuthError("invalid_credentials")

        issued = await self.issue_tenant_session(
            session,
            tenant=tenant,
            user=user,
            user_agent=user_agent,
            client_address=client_address,
        )
        stored.revoked_at = now
        stored.last_used_at = now
        await session.flush()
        return issued

    async def revoke_tenant_session(self, session: AsyncSession, *, refresh_token: str) -> None:
        """Sign out. Idempotent, and silent about a token that was never valid."""
        try:
            realm, user_id, session_id, tenant_id = self._tokens.verify_session_token(
                refresh_token, token_type=TokenType.REFRESH
            )
        except Exception:  # an unverifiable token is simply nothing to revoke
            return
        if realm is not Realm.TENANT or tenant_id is None:
            return

        await bind_tenant(session, tenant_id)
        stored = await session.scalar(
            select(RefreshSession).where(RefreshSession.refresh_session_id == session_id)
        )
        if stored is not None and stored.tenant_user_id == user_id:
            stored.revoked_at = utcnow()
            await session.flush()

    # --------------------------------------------- user administration

    async def change_user_role(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        target_user_id: uuid.UUID,
        new_role: str,
    ) -> TenantUser:
        user = await self._locked_user(session, target_user_id)
        if user.is_administrator and new_role != TenantRole.TENANT_ADMINISTRATOR.value:
            await self._refuse_if_last_administrator(session, tenant_id, user)
        user.role = new_role
        await session.flush()
        return user

    async def set_user_status(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        target_user_id: uuid.UUID,
        new_status: str,
    ) -> TenantUser:
        user = await self._locked_user(session, target_user_id)
        if new_status == user.status and new_status == UserStatus.DISABLED.value:
            raise ConflictError("user_already_disabled")
        if user.is_administrator and new_status != UserStatus.ACTIVE.value:
            await self._refuse_if_last_administrator(session, tenant_id, user)
        user.status = new_status
        await session.flush()
        return user

    async def _locked_user(self, session: AsyncSession, user_id: uuid.UUID) -> TenantUser:
        """Load the target under a row lock. Gate 4 is the database's job here.

        The query carries no `tenant_id` predicate on purpose: the session is
        bound, so a foreign identifier returns no row and becomes a 404 — the
        same answer a genuinely absent one gets.
        """
        user = await session.scalar(
            select(TenantUser).where(TenantUser.tenant_user_id == user_id).with_for_update()
        )
        if user is None:
            raise NotFoundError()
        return user

    async def _refuse_if_last_administrator(
        self, session: AsyncSession, tenant_id: uuid.UUID, target: TenantUser
    ) -> None:
        """The rule the prototype states at dc.html L1244, enforced correctly.

        Counting without a lock is a race that loses a tenant: two administrators
        demoted concurrently each see the other and each proceed. `_locked_user`
        has already taken a `FOR UPDATE` lock on the target, and this counts the
        *other* active administrators under the same transaction — so the second
        demotion blocks until the first commits, then correctly sees a count of
        zero and refuses.
        """
        # The rows are selected and locked, then counted in Python. `SELECT
        # count(*) ... FOR UPDATE` is rejected by PostgreSQL — a lock applies to
        # rows, and an aggregate returns none — and without the lock this is a
        # race that loses a tenant: two administrators demoted concurrently each
        # see the other and each proceed.
        remaining = (
            await session.scalars(
                select(TenantUser.tenant_user_id)
                .where(
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.tenant_user_id != target.tenant_user_id,
                    TenantUser.role == TenantRole.TENANT_ADMINISTRATOR.value,
                    TenantUser.status == UserStatus.ACTIVE.value,
                )
                .with_for_update()
            )
        ).all()
        if not remaining:
            raise ConflictError("last_active_administrator")

    async def create_user(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        email: str,
        display_name: str,
        role: str,
        invited_by: uuid.UUID | None = None,
    ) -> IssuedInvitation:
        """Invite someone. The account exists immediately; it cannot yet sign in.

        Two rows, one transaction: an `invited` `TenantUser` so the console can
        list the person straight away (dc.html L1236), and an `Invitation`
        holding the digest of the token that will activate them.

        The administrator chooses the role here and the invitee cannot change it
        — `accept_invitation` reads the role from the invitation row, never from
        the accepting request.

        No `WHERE tenant_id` on the conflict check, and none needed: the session
        is bound, so "already exists" means "already exists in this tenant",
        which is exactly what the prototype's message claims (dc.html L1235).
        """
        normalised = email.strip().lower()
        if not normalised:
            raise ValidationError("email_required").with_field(
                "email", "An email is required — it is the account identifier."
            )
        clash = await session.scalar(
            select(func.count()).select_from(TenantUser).where(TenantUser.email == normalised)
        )
        if clash:
            raise ConflictError("user_already_exists")

        user = TenantUser(
            tenant_user_id=uuid7(),
            tenant_id=tenant_id,
            email=normalised,
            display_name=display_name.strip() or normalised.split("@", 1)[0],
            # Not a hash of anything: no password exists yet. The digest is a
            # deliberately unusable placeholder, and the account is `invited`, so
            # `can_authenticate` refuses regardless.
            credential_digest="!invited",
            role=role,
            status=UserStatus.INVITED.value,
        )
        session.add(user)

        token = f"{INVITATION_TOKEN_PREFIX}{new_token()}"
        invitation = Invitation(
            invitation_id=uuid7(),
            tenant_id=tenant_id,
            email=normalised,
            role=role,
            token_digest=digest_token(token),
            invited_by=invited_by,
            expires_at=utcnow() + self._invitation_ttl,
        )
        session.add(invitation)
        await session.flush()
        return IssuedInvitation(user=user, invitation=invitation, token=token)

    # -------------------------------------------------------- accepting one

    async def accept_invitation(
        self,
        session: AsyncSession,
        *,
        token: str,
        password: str,
        password_confirmation: str,
    ) -> TenantUser:
        """Turn an invitation into an active account. Runs with no credential.

        The order is the security property:

        1. Compare the confirmation. It reveals nothing about any invitation, so
           it is free to check first, and checking it last would mean a mistyped
           password consumed the invitation before the mismatch was noticed.
        2. Digest the token and resolve its tenant through
           `tenant_lookup.resolve_invitation` (migration 0004). The token itself
           never reaches the database.
        3. Bind the tenant context, and only then read anything. Every read below
           this line is filtered by the same policy that filters tenant traffic.
        4. Apply the lifecycle rules — expired, revoked, already accepted — under
           a row lock, so two people racing the same link cannot both win.

        Every refusal is `invitation_invalid`, whatever the cause: the prototype
        promises that "expired or invalid tokens are rejected without disclosing
        account details" (dc.html L1046). A distinct "already accepted" would
        disclose that the account exists and is live.
        """
        if password != password_confirmation:
            raise ValidationError("password_confirmation_mismatch").with_field(
                "password_confirmation",
                "The new authentication material and its confirmation do not match.",
            )

        digest = digest_token(token)
        tenant_id = await session.scalar(select(func.tenant_lookup.resolve_invitation(digest)))
        if tenant_id is None:
            raise AuthError("invitation_invalid")

        await bind_tenant(session, tenant_id)

        invitation = await session.scalar(
            select(Invitation).where(Invitation.token_digest == digest).with_for_update()
        )
        # Not impossible: the resolver runs unbound, this read runs bound, and a
        # tenant deleted between the two leaves the row unreachable. Same answer.
        if invitation is None or not invitation.is_open(utcnow()):
            raise AuthError("invitation_invalid")

        user = await session.scalar(
            select(TenantUser).where(TenantUser.email == invitation.email).with_for_update()
        )
        if user is None or user.status != UserStatus.INVITED.value:
            # An administrator who locked the account before it was ever
            # activated has decided; the invitation does not overrule that.
            raise AuthError("invitation_invalid")

        user.credential_digest = hash_password(password)
        # The role comes from the invitation, not from the accepting request.
        user.role = invitation.role
        user.status = UserStatus.ACTIVE.value
        invitation.accepted_at = utcnow()
        await session.flush()
        return user
