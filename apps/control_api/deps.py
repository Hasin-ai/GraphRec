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
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Iterable,
)
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graphrec.auth.api_keys import PREFIX_NAMESPACE
from graphrec.auth.tokens import PlatformClaims, TenantClaims, TokenError, TokenService
from graphrec.common.config import Settings
from graphrec.common.enums import (
    CredentialScope,
    PlatformPermission,
    TenantRole,
    TenantStatus,
)
from graphrec.common.errors import AuthError, ForbiddenError, NotFoundError
from graphrec.common.logging import actor_id_var, tenant_id_var
from graphrec.db.models import ApiKey, PlatformUser, Tenant, TenantUser
from graphrec.db.tenant_context import bind_tenant
from graphrec.domain.audit import Actor, AuditTrail
from graphrec.domain.credentials import CredentialService
from graphrec.domain.metering.counters import UsageCounters
from graphrec.http.rate_limit import Limit, RateLimiter

T = TypeVar("T")

#: `auto_error=False` so a missing header reaches our handler rather than
#: FastAPI's, which would emit `{"detail": ...}` instead of the envelope.
_bearer = HTTPBearer(auto_error=False)


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


def get_usage_counters(request: Request) -> UsageCounters:
    """The fast counters, built once at startup.

    Wrapped in `ResilientUsageCounters` there, so a handler never has to think
    about Redis being down: a failed read is a miss, and a miss is recomputed
    from the ledger.
    """
    counters: UsageCounters = request.app.state.usage_counters
    return counters


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


async def _tenant_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    tokens: TokenService,
    *,
    require_operable: bool,
) -> AsyncGenerator[TenantPrincipal, None]:
    """Gate 1 for the tenant realm, gate 2 when asked, and the context binding.

    Annotated `AsyncGenerator` rather than `AsyncIterator` because the two
    wrappers below hand it to `contextlib.aclosing`, which needs `aclose` in the
    type and not merely at runtime. Widening this back to `AsyncIterator` breaks
    them, and the reason it breaks them is the reason they exist.

    The sequence matters. The token is verified first, because until it is, `tid`
    is attacker-controlled bytes. Only then is it used to bind `app.tenant_id`,
    and every query afterwards — including the one that loads the tenant itself —
    runs inside that binding.

    `require_operable` is the only thing that varies, and only two callers ever
    set it false — see `current_tenant_principal_any_state` for why the exemption
    exists and why it is this narrow.
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
        if require_operable and not tenant.is_operable:
            raise ForbiddenError("tenant_not_active")

        if not user.can_authenticate:
            # A session outliving the account being disabled. The access
            # token is still cryptographically valid; the account is not.
            raise AuthError("invalid_credentials")

        tenant_id_var.set(str(claims.tenant_id))
        actor_id_var.set(str(claims.user_id))

        yield TenantPrincipal(claims=claims, user=user, tenant=tenant, session=bound)


async def current_tenant_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> AsyncIterator[TenantPrincipal]:
    """Gates 1 and 2. What every tenant-realm route uses, with two exceptions.

    `aclosing` is load-bearing, not decoration. FastAPI finalises a dependency
    generator by throwing `GeneratorExit` in at the `yield`; that unwinds this
    frame but leaves the inner generator suspended inside its own `async with
    sessionmaker()`. Nothing then closes the session, and the connection lives
    until the garbage collector reaps it — which surfaces, much later and in
    some unrelated test, as `BaseConnection.__del__` complaining. Closing the
    inner generator here keeps the session's lifetime tied to the request's.
    """
    inner = _tenant_principal(request, credentials, tokens, require_operable=True)
    async with aclosing(inner) as gate:
        async for principal in gate:
            yield principal


async def current_tenant_principal_any_state(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> AsyncIterator[TenantPrincipal]:
    """Gate 1 without gate 2. The exemption `GET /v1/tenant` needs to exist at all.

    Gate 2 sends a member of a non-active tenant to `/account/tenant-status`,
    which "states the tenant's lifecycle position and that a Platform
    Administrator controls the transition" (FRONTEND_BUILD_PROMPT §7). That page
    has to read the status from somewhere, and the only endpoint that carries it
    is this one — so a `GET /v1/tenant` behind gate 2 makes the gate-2 landing
    page unrenderable, which is exactly the circularity `docs/BUILD_PROMPT.md`
    L372 forecloses: *403 `tenant_not_active` on everything **except**
    `/v1/auth/*` and `GET /v1/tenant`*.

    The exemption is narrow on purpose:

    * Gate 1 is unchanged. An unauthenticated caller still gets 401, and a token
      for another tenant still resolves to nothing under RLS.
    * The disabled-account check is unchanged. A locked user of a suspended
      tenant is refused here, not shown a status page.
    * It exempts **one read**. Nothing that writes, and nothing that returns a
      tenant-owned resource, may use this. A suspended tenant's products,
      credentials and jobs are all still behind gate 2, which is the point of
      suspending it.
    """
    inner = _tenant_principal(request, credentials, tokens, require_operable=False)
    async with aclosing(inner) as gate:
        async for principal in gate:
            yield principal


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
    # One transaction for the whole request, exactly as the tenant realm gets.
    # The platform realm reached Phase 12 with nothing to commit, so this was a
    # bare session; it now suspends tenants, edits plans and grants overrides,
    # and each of those has to land with its audit row or not at all.
    async with sessionmaker() as session, session.begin():
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


# ------------------------------------------------------------- rate limits


def _peer(request: Request) -> str:
    """The caller key for a limit that applies before anybody is authenticated.

    `request.client.host`, never `X-Forwarded-For` — the same rule
    `auth.py::_client_address` follows and for the same reason: the header is
    caller-controlled unless a trusted proxy overwrites it, and a spoofable key
    is a limit that can be reset at will by the one caller it exists to slow.

    Caddy sets the peer address on both edges (`trusted_proxies`), so behind the
    real deployment this is the client. Behind a proxy that does not, every
    caller shares one bucket — which fails towards refusing too much rather than
    too little, and is visible immediately.
    """
    return request.client.host if request.client else "unknown"


def rate_limit(name: str) -> Callable[[Request], Awaitable[None]]:
    """A dependency that counts one request against the named class.

    A factory rather than five copies, because the five settings are already
    named by convention (`<name>_rate_limit`, `<name>_rate_window_seconds`) and
    a hand-written dependency per class is five places for the wrong setting to
    be read. The lookup is `getattr`, so a class whose settings do not exist
    fails at import in the test that walks the five names, not at the first
    request in production.
    """

    async def _dependency(request: Request) -> None:
        settings: Settings = request.app.state.settings
        limit = Limit(
            name=name,
            limit=getattr(settings, f"{name}_rate_limit"),
            window_seconds=getattr(settings, f"{name}_rate_window_seconds"),
        )
        limiter: RateLimiter = request.app.state.rate_limiter
        await limiter.check(limit, _peer(request))

    return _dependency


def tenant_rate_limit(name: str) -> Callable[..., Awaitable[None]]:
    """The same, keyed on the tenant rather than on the address.

    Everything past sign-in has an identity better than an address: a console
    behind one office NAT would otherwise share a bucket between every employee,
    and a tenant on a residential connection would get a new allowance whenever
    their address changed. The dependency takes `CurrentTenant`, so the limit is
    applied after authentication and before the handler.
    """

    async def _dependency(request: Request, principal: CurrentTenant) -> None:
        settings: Settings = request.app.state.settings
        limit = Limit(
            name=name,
            limit=getattr(settings, f"{name}_rate_limit"),
            window_seconds=getattr(settings, f"{name}_rate_window_seconds"),
        )
        limiter: RateLimiter = request.app.state.rate_limiter
        await limiter.check(limit, str(principal.tenant_id))

    return _dependency


#: The five §24 classes, as dependencies. Named here rather than at each route so
#: that "which endpoints are limited?" is one grep against one list.
LoginRateLimit = Depends(rate_limit("login"))
RegistrationRateLimit = Depends(rate_limit("registration"))
ApiKeyRateLimit = Depends(tenant_rate_limit("api_key"))
UsageRateLimit = Depends(tenant_rate_limit("usage"))
SubscriptionRateLimit = Depends(tenant_rate_limit("subscription"))


UsageCountersDep = Annotated[UsageCounters, Depends(get_usage_counters)]

CurrentTenant = Annotated[TenantPrincipal, Depends(current_tenant_principal)]
CurrentPlatform = Annotated[PlatformPrincipal, Depends(current_platform_principal)]
CurrentCredential = Annotated[CredentialPrincipal, Depends(current_credential_principal)]


def tenant_audit(principal: CurrentTenant, request: Request) -> AuditTrail:
    """The tenant realm's audit writer.

    Carries two things a handler cannot get from the principal alone: the actor
    in the four-value vocabulary the table stores, and the sessionmaker a
    *refused* action needs — a refusal's row cannot be written into the
    transaction that is about to roll back (`domain/audit/trail.py`).
    """
    return AuditTrail(
        session=principal.session,
        sessionmaker=request.app.state.sessionmaker,
        actor=Actor.user(principal.user_id),
        tenant_id=principal.tenant_id,
    )


def platform_audit(principal: CurrentPlatform, request: Request) -> AuditTrail:
    """The platform realm's audit writer, concerning no tenant yet.

    `tenant_id` is `None` here and a handler acting on a tenant calls
    `.concerning(tenant_id)`. That is not ceremony: an operator listing plans
    acts on nothing tenant-shaped, and defaulting the column to the subject of
    the path would attribute a plan edit to whichever tenant happened to be in
    the URL of a different route.

    The refusal connection is the platform sessionmaker, which connects as
    `graphrec_platform` — the role whose policy on `audit_logs` is
    `WITH CHECK (true)`, because the platform realm never sets `app.tenant_id`.
    """
    return AuditTrail(
        session=principal.session,
        sessionmaker=request.app.state.platform_sessionmaker,
        actor=Actor.platform(principal.user_id),
    )


TenantAudit = Annotated[AuditTrail, Depends(tenant_audit)]
PlatformAudit = Annotated[AuditTrail, Depends(platform_audit)]


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


# ----------------------------------------------- the ingest realms, together
#
# Ingestion is the one surface both realms legitimately reach. A developer uses
# the console's Test event form (dc.html L1621) and its bulk upload; an
# integration uses a credential from the tenant's own backend. Both are the same
# operation on the same data, so there is one route, not two.
#
# The realms are told apart by the shape of what was presented, not by a header
# the caller chose and not by a query parameter. A credential secret begins with
# `gr_live_`; a session access token is a JWT and cannot. This is a *routing*
# decision only — it selects which verifier runs, and that verifier still has to
# succeed. Presenting a string that starts with `gr_live_` skips nothing; it
# merely guarantees the answer comes from `CredentialService.verify`.


@dataclass(frozen=True, slots=True)
class IngestPrincipal:
    """Whoever is submitting, reduced to what an ingest handler may use.

    Deliberately narrow. It carries a tenant, a bound session and the name of
    the realm it came from — and no role and no scopes. A handler that reached
    for one of those would be making an authorization decision below the gates,
    which is where authorization decisions go wrong.

    `tenant_id` came from a verified token's `tid` claim or from a verified
    credential's own row. There is no third path.
    """

    tenant_id: uuid.UUID
    session: AsyncSession
    #: `"session"` or `"credential"`. For attribution, never for authority.
    realm: str
    #: The credential's key id, or `None` for a session. The audit trail has to
    #: be able to name *which* credential submitted a batch, because revoking
    #: one is the remedy when a submission turns out to be wrong.
    key_id: uuid.UUID | None = None
    actor_user_id: uuid.UUID | None = None


#: Wrapped so that the delegation below both commits on success and rolls back
#: on failure. An `async for` over the raw generator would do neither: the inner
#: generator would be left suspended at its `yield`, inside an open transaction,
#: waiting for a garbage collector to decide the tenant's data's fate.
_tenant_realm = asynccontextmanager(current_tenant_principal)
_credential_realm = asynccontextmanager(current_credential_principal)


def require_ingest(
    *scopes: CredentialScope,
    roles: tuple[TenantRole, ...] = (TenantRole.TENANT_DEVELOPER,),
) -> Callable[..., AsyncIterator[IngestPrincipal]]:
    """Accept either realm, and apply gate 3 in whichever one answered.

    The two gate-3 checks are not the same check and must not be collapsed into
    one. A session is judged by **role**, because the prototype's route table
    marks every ingest screen `[DEV]` and L1256 states an administrator has "no
    event submission". A credential is judged by **scope**, because a program
    holds operations rather than a job title. Mapping scopes onto roles — or
    roles onto scopes — would mean an administrator's session could be described
    as holding `events:write`, which the tenant never granted it.

    Gates 1 and 2 are unchanged in both realms: this delegates to the existing
    principals rather than re-implementing verification, so there is still
    exactly one place in the codebase where a token becomes a tenant.
    """
    required = frozenset(scopes)
    allowed = {role.value for role in roles}

    async def _guard(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        tokens: Annotated[TokenService, Depends(get_token_service)],
        settings: Annotated[Settings, Depends(get_settings_dep)],
    ) -> AsyncIterator[IngestPrincipal]:
        presented = _bearer_token(credentials, "invalid_credentials")

        if presented.startswith(PREFIX_NAMESPACE):
            async with _credential_realm(request, credentials, settings) as credential:
                if not required.issubset(credential.scopes):
                    raise ForbiddenError("insufficient_scope")
                yield IngestPrincipal(
                    tenant_id=credential.tenant_id,
                    session=credential.session,
                    realm="credential",
                    key_id=credential.key_id,
                )
            return

        async with _tenant_realm(request, credentials, tokens) as principal:
            if principal.role not in allowed:
                raise ForbiddenError("insufficient_role")
            yield IngestPrincipal(
                tenant_id=principal.tenant_id,
                session=principal.session,
                realm="session",
                actor_user_id=principal.user_id,
            )

    return _guard


# --------------------------------------------------- gate 5: resource state
#
# Gate 5 lives in the domain services rather than here: whether a version may be
# activated, or a job cancelled, is a question about that resource's lifecycle,
# and the answer belongs next to the lifecycle. What this module fixes is that
# gate 5 runs *last* — a 409 is only ever reached by an actor who is
# authenticated, whose tenant is active, who holds the role, and who owns the
# resource. A 409 therefore never tells anyone anything they did not already know.


__all__ = [
    "AuditTrail",
    "CurrentPlatform",
    "CurrentTenant",
    "ForbiddenError",
    "IngestPrincipal",
    "PlatformAudit",
    "PlatformPrincipal",
    "RequireAdministrator",
    "TenantAudit",
    "TenantPrincipal",
    "TenantStatus",
    "current_platform_principal",
    "current_tenant_principal",
    "current_tenant_principal_any_state",
    "get_session",
    "get_settings_dep",
    "get_token_service",
    "require_ingest",
    "require_owned",
    "require_permission",
    "require_role",
]
