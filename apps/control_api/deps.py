"""The authorization gates, in the order they must run.

Five gates, and the order is the security property — not a style choice:

1. **Identity.** Is the credential real? Failure is 401.
2. **Tenant state.** Is the tenant permitted to act at all? Failure is 403.
3. **Role / permission.** Does this actor hold the operation? Failure is 403.
4. **Ownership.** Does the resource belong to this tenant? Failure is **404**.
5. **Resource state.** Is the resource in a state that allows it? Failure is 409.

Running them out of order leaks. If ownership (4) ran before role (3), a
developer probing an administrator-only route would learn which identifiers exist
in their own tenant before being told they lack the role — minor. The serious
inversion is the other way: answering 403-for-role on a resource that belongs to
*another tenant* confirms that resource exists. Gate 4 therefore never returns
403, and its 404 never names what was not found.

Gate 4 is mostly not enforced here. It is enforced by the database: every query
runs bound to `app.tenant_id`, so a foreign row is not filtered out after being
read — it is never returned. `require_owned` exists for the residue where a
handler holds an identifier and must turn "no row" into the right 404.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, TypeVar

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graphrec.auth.tokens import PlatformClaims, TenantClaims, TokenError, TokenService
from graphrec.common.enums import (
    CredentialScope,
    PlatformPermission,
    TenantRole,
    TenantStatus,
)
from graphrec.common.errors import AuthError, ErrorClass, GraphRecError, NotFoundError
from graphrec.common.logging import actor_id_var, tenant_id_var
from graphrec.db.models import ApiKey, PlatformUser, Tenant, TenantUser
from graphrec.db.tenant_context import bind_tenant
from graphrec.domain.credentials import CredentialService

if TYPE_CHECKING:
    from graphrec.common.config import Settings

T = TypeVar("T")

#: `auto_error=False` so a missing header reaches our handler rather than
#: FastAPI's, which would emit `{"detail": ...}` instead of the envelope.
_bearer = HTTPBearer(auto_error=False)


class ForbiddenError(GraphRecError):
    """403 — the actor is known, and is not allowed.

    Distinct from `AuthError` (401, "we do not know who you are") and from
    `NotFoundError` (404, "it is not yours, and we will not say more"). Used only
    for gates 2 and 3, where the resource in question is the tenant's own.
    """

    error_class = ErrorClass.AUTH
    code = "insufficient_role"
    status_code = 403


@dataclass(frozen=True, slots=True)
class TenantPrincipal:
    """A verified tenant actor, with the tenant loaded and checked.

    `tenant_id` on this object is the only tenant identifier a handler may use.
    It came from the `tid` claim of a signature-verified token. There is no
    constructor path that takes one from a request.
    """

    claims: TenantClaims
    user: TenantUser
    tenant: Tenant
    #: The session this principal was loaded on, already bound to `tenant_id` and
    #: inside an open transaction. Handlers reuse it rather than opening their
    #: own, because a second, unbound session would see nothing at best and
    #: everything at worst.
    session: AsyncSession

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.claims.tenant_id

    @property
    def user_id(self) -> uuid.UUID:
        return self.claims.user_id

    @property
    def role(self) -> str:
        return self.user.role

    @property
    def is_administrator(self) -> bool:
        return self.role == TenantRole.TENANT_ADMINISTRATOR.value


@dataclass(frozen=True, slots=True)
class CredentialPrincipal:
    """An application authenticated by an API credential, not by a session.

    A third realm, alongside tenant users and platform operators. It carries a
    `tenant_id` like a tenant user does, but it carries **scopes instead of a
    role**, and the two are not interchangeable: a role says which screens a
    person may open, a scope says which operations a program may perform. There
    is deliberately no `role` property here, so a handler cannot accidentally
    treat a credential as an administrator.
    """

    api_key: ApiKey
    scopes: frozenset[CredentialScope]
    session: AsyncSession
    used_grace_secret: bool

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.api_key.tenant_id

    @property
    def key_id(self) -> uuid.UUID:
        return self.api_key.key_id

    def has(self, scope: CredentialScope) -> bool:
        return scope in self.scopes


@dataclass(frozen=True, slots=True)
class PlatformPrincipal:
    """A verified operator. Deliberately has no `tenant_id` property at all.

    Not "returns None" — absent. A handler that tries to read one fails at import
    or attribute access rather than silently operating on `None`, and a platform
    route that wants to act on a tenant has to name it explicitly.
    """

    claims: PlatformClaims
    user: PlatformUser
    session: AsyncSession

    @property
    def user_id(self) -> uuid.UUID:
        return self.claims.user_id

    @property
    def permissions(self) -> frozenset[str]:
        return self.claims.permissions

    def holds(self, permission: PlatformPermission) -> bool:
        return permission.value in self.permissions


# --------------------------------------------------------------- wiring


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_token_service(request: Request) -> TokenService:
    service: TokenService = request.app.state.tokens
    return service


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """An unbound session — no tenant context. For sign-in and registration only.

    Every route that serves an authenticated tenant must depend on
    `tenant_session` instead, which binds the context. This one exists because
    sign-in has to find a user before there is any verified tenant to bind to,
    and it is deliberately named so that its use stands out in a diff.
    """
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


def _bearer_token(credentials: HTTPAuthorizationCredentials | None, code: str) -> str:
    """Extract the bearer token, or fail with the realm's one message.

    A missing header, a non-bearer scheme and an unverifiable token all raise the
    same `code`. There is no separate "credentials required" message, for two
    reasons: the prototype approves no such copy, and distinguishing the cases
    tells a caller whether the thing they sent was *shaped* like a credential —
    which is a small oracle, freely given.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError(code)
    return credentials.credentials


# ------------------------------------------------------- gate 1: identity


async def current_tenant_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> AsyncIterator[TenantPrincipal]:
    """Gates 1 and 2 for the tenant realm, and it binds the database context.

    The sequence matters. The token is verified first, because until it is, `tid`
    is attacker-controlled bytes. Only then is it used to bind `app.tenant_id`,
    and every query afterwards — including the one that loads the tenant itself —
    runs inside that binding.
    """
    token = _bearer_token(credentials, "invalid_credentials")
    try:
        claims = tokens.verify_tenant_access(token)
    except TokenError as exc:
        # One message for expired, forged, wrong-realm and wrong-type. The
        # difference is a log line, never a response body.
        raise AuthError("invalid_credentials") from exc

    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as bound, bound.begin():
        await bind_tenant(bound, claims.tenant_id)

        tenant = await bound.scalar(select(Tenant).where(Tenant.tenant_id == claims.tenant_id))
        user = await bound.scalar(
            select(TenantUser).where(TenantUser.tenant_user_id == claims.user_id)
        )

        # A tenant deleted, or a user removed, after the token was issued.
        # RLS also means a `tid` naming someone else's tenant returns nothing
        # here — the forged-token case lands on the same branch.
        if tenant is None or user is None:
            raise AuthError("invalid_credentials")

        # ------------------------------------------- gate 2: tenant state
        if not tenant.is_operable:
            raise ForbiddenError("tenant_not_active")

        if not user.can_authenticate:
            # A session outliving the account being disabled. The access
            # token is still cryptographically valid; the account is not.
            raise AuthError("invalid_credentials")

        tenant_id_var.set(str(claims.tenant_id))
        actor_id_var.set(str(claims.user_id))

        yield TenantPrincipal(claims=claims, user=user, tenant=tenant, session=bound)


# --------------------------------------- gate 1: identity, credential realm


async def current_credential_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AsyncIterator[CredentialPrincipal]:
    """Gates 1 and 2 for the credential realm.

    Same shape as the tenant realm and the same ordering guarantee: nothing
    tenant-owned is read until the context is bound, and the context is bound
    from the credential rather than from anything the caller asserted. The
    difference is that the binding happens *inside* `CredentialService.verify`,
    because resolving a prefix to a tenant is itself a pre-credential lookup.

    A session token presented here is refused, exactly as an API credential
    presented to a session route is refused. The realms do not meet.
    """
    presented = _bearer_token(credentials, "invalid_credentials")

    service = CredentialService(
        pepper=settings.api_key_hmac_pepper.get_secret_value(),
        hash_version=settings.api_key_hash_version,
        max_active_per_tenant=settings.max_active_api_keys_per_tenant,
        max_scopes=settings.max_api_key_scopes,
        max_name_length=settings.max_api_key_name_length,
        max_grace_seconds=settings.max_api_key_grace_seconds,
    )

    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as bound, bound.begin():
        verified = await service.verify(bound, presented=presented)

        tenant = await bound.scalar(select(Tenant).where(Tenant.tenant_id == verified.tenant_id))
        if tenant is None:
            raise AuthError("invalid_credentials")

        # ----------------------------------------- gate 2: tenant state
        if not tenant.is_operable:
            raise ForbiddenError("tenant_not_active")

        tenant_id_var.set(str(verified.tenant_id))
        # The credential, not a person, is the actor. Recorded as the key id so
        # the audit trail names which credential acted — never the secret and
        # never the prefix, which would put a live identifier into every log.
        actor_id_var.set(str(verified.api_key.key_id))

        yield CredentialPrincipal(
            api_key=verified.api_key,
            scopes=verified.scopes,
            session=bound,
            used_grace_secret=verified.used_grace_secret,
        )


async def current_platform_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> AsyncIterator[PlatformPrincipal]:
    """Gate 1 for the platform realm, on the platform connection.

    Uses `platform_sessionmaker`, which connects as `graphrec_platform`. That role
    holds no grant at all on products, events, customers or models, so a bug in a
    platform handler cannot read tenant business data — the privilege is missing,
    not merely unexercised.
    """
    token = _bearer_token(credentials, "invalid_platform_credentials")
    try:
        claims = tokens.verify_platform_access(token)
    except TokenError as exc:
        raise AuthError("invalid_platform_credentials") from exc

    sessionmaker = request.app.state.platform_sessionmaker
    async with sessionmaker() as session:
        user = await session.scalar(
            select(PlatformUser).where(PlatformUser.platform_user_id == claims.user_id)
        )
        if user is None or not user.can_authenticate:
            raise AuthError("invalid_platform_credentials")

        # The token's `perms` are re-checked against the database rather than
        # trusted alone. A permission revoked an hour ago must not survive in a
        # token issued before the revocation.
        granted = user.granted()
        effective = claims.permissions & granted

        actor_id_var.set(str(claims.user_id))
        # Note there is no `tenant_id_var.set` here, and no tenant to set it to.

        yield PlatformPrincipal(
            claims=PlatformClaims(
                user_id=claims.user_id,
                permissions=frozenset(effective),
                token_id=claims.token_id,
                expires_at=claims.expires_at,
            ),
            user=user,
            session=session,
        )


CurrentTenant = Annotated[TenantPrincipal, Depends(current_tenant_principal)]
CurrentPlatform = Annotated[PlatformPrincipal, Depends(current_platform_principal)]
CurrentCredential = Annotated[CredentialPrincipal, Depends(current_credential_principal)]


# ------------------------------------------------- gate 3: role / permission


def require_role(
    *roles: TenantRole,
) -> Callable[[TenantPrincipal], Coroutine[Any, Any, TenantPrincipal]]:
    """Require one of the named tenant roles. Gate 3.

    Returns 403 with the prototype's wording: "Your role or named permission does
    not include this operation. There is nothing to retry here." (dc.html L1063)
    — the last sentence matters, because it tells the console not to offer a
    retry for a refusal that will never change on its own.
    """
    allowed = {role.value for role in roles}

    async def _guard(principal: CurrentTenant) -> TenantPrincipal:
        if principal.role not in allowed:
            raise ForbiddenError("insufficient_role")
        return principal

    return _guard


def require_scope(
    *scopes: CredentialScope,
) -> Callable[[CredentialPrincipal], Coroutine[Any, Any, CredentialPrincipal]]:
    """Require **all** the named scopes. Gate 3 for the credential realm.

    All rather than any, for the same reason `require_permission` intersects: a
    route that declares two scopes is stating that it performs two kinds of
    operation, and a credential holding one of them is not entitled to the
    other. "Any of" would let a read-only credential reach a route that also
    writes.

    The refusal is the prototype's, at dc.html L1170: "Only the operations
    granted to a credential may be performed with it. Anything else is rejected
    before the operation is accepted." *Before it is accepted* is a promise
    about ordering — the check runs ahead of the work, so a refused call has no
    side effects and consumes no quota.
    """
    required = frozenset(scopes)

    async def _guard(principal: CurrentCredential) -> CredentialPrincipal:
        if not required.issubset(principal.scopes):
            raise ForbiddenError("insufficient_scope")
        return principal

    return _guard


def refuse_scope_delegation(
    granted: frozenset[CredentialScope], requested: Iterable[CredentialScope]
) -> None:
    """A credential may never issue authority it does not itself hold.

    This is the containment property that makes scopes worth having. Without
    it, a credential holding only `events:write` could mint a second credential
    holding `recommendations:read`, and the scope on the first one would be
    advisory rather than binding — one compromised low-privilege credential
    would escalate to every scope in the vocabulary.

    In Phase 3 the credential-management routes are session-only, so no
    credential reaches them and this function has no live call site on the
    request path. It is written and tested now because the moment a
    machine-to-machine provisioning route is added — and BACKEND_PLAN §12.3
    anticipates one — the check has to already exist. A guard introduced at the
    same time as the route it guards is a guard nobody reviews.
    """
    escalation = frozenset(requested) - granted
    if escalation:
        # The refusal never names which scope was over-reached. Naming it would
        # confirm the vocabulary to a caller probing what else exists.
        raise ForbiddenError("insufficient_scope")


def require_permission(
    *permissions: PlatformPermission,
) -> Callable[[PlatformPrincipal], Coroutine[Any, Any, PlatformPrincipal]]:
    """Require **all** the named platform permissions. Gate 3.

    All rather than any, deliberately. The five permissions are independently
    grantable, so a route that needs two is asking for the intersection; treating
    the list as "any of" would let a monitoring-only operator reach a route that
    also requires plan management.
    """
    required = {permission.value for permission in permissions}

    async def _guard(principal: CurrentPlatform) -> PlatformPrincipal:
        if not required <= principal.permissions:
            raise ForbiddenError("insufficient_role")
        return principal

    return _guard


RequireAdministrator = Annotated[
    TenantPrincipal, Depends(require_role(TenantRole.TENANT_ADMINISTRATOR))
]


# ------------------------------------------------------- gate 4: ownership


def require_owned(instance: T | None) -> T:
    """Turn "the bound query returned nothing" into the correct 404.

    There is no `tenant_id` argument, and that is the point: the query was
    already bound, so a foreign row was never a candidate. A version of this that
    compared `instance.tenant_id` to an expected value would be a second,
    weaker copy of a check the database has already made — and the copy is what
    drifts.
    """
    if instance is None:
        raise NotFoundError()
    return instance


# --------------------------------------------------- gate 5: resource state
#
# Gate 5 lives in the domain services rather than here: whether a version may be
# activated, or a job cancelled, is a question about that resource's lifecycle,
# and the answer belongs next to the lifecycle. What this module fixes is that
# gate 5 runs *last* — a 409 is only ever reached by an actor who is
# authenticated, whose tenant is active, who holds the role, and who owns the
# resource. A 409 therefore never tells anyone anything they did not already know.


__all__ = [
    "CurrentPlatform",
    "CurrentTenant",
    "ForbiddenError",
    "PlatformPrincipal",
    "RequireAdministrator",
    "TenantPrincipal",
    "TenantStatus",
    "current_platform_principal",
    "current_tenant_principal",
    "get_session",
    "get_settings_dep",
    "get_token_service",
    "require_owned",
    "require_permission",
    "require_role",
]
