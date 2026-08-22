"""Authenticating with a credential, and the rotation grace window.

These exercise `CredentialService.verify` directly rather than through a route.
Phase 3 ships no route that *accepts* a credential — the first one lands in
Phase 5 — but verification is the piece with the widest blast radius, so it is
pinned now rather than when its first caller appears.

Every test here runs inside one open transaction on a throwaway tenant, and the
transaction is rolled back at the end. That is not only for cleanliness: the
tenant context is `SET LOCAL`, so committing would drop the binding and every
subsequent statement would be filtered by a policy resolving `NULL`. Working
inside the transaction is what the request path does too.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from graphrec.common.enums import CredentialScope, TenantStatus
from graphrec.common.errors import AuthError, ConflictError, LimitError, ValidationError
from graphrec.db.models import ApiKey
from graphrec.db.tenant_context import bind_tenant
from graphrec.domain.credentials import CredentialService
from tests.authz.conftest import auth

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.authz

PEPPER = "a-pepper-for-the-tests-only"


def _service(**kwargs: int) -> CredentialService:
    return CredentialService(pepper=PEPPER, hash_version=1, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
async def tenant_session(settings, owner_engine):
    """An `AsyncSession` as `graphrec_app`, bound to a tenant of its own.

    A fresh tenant rather than the shared `realm` one, because the cap tests
    below count the credentials in the bound tenant and would otherwise be
    counting rows left behind by `test_credentials.py`.
    """
    engine = create_async_engine(settings.database_url, poolclass=sa.pool.NullPool)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    suffix = tenant_id.hex[:8]

    try:
        async with sessionmaker() as session:
            await session.begin()
            await bind_tenant(session, tenant_id)
            await session.execute(
                sa.text(
                    "INSERT INTO tenants (tenant_id, tenant_code, tenant_name, status) "
                    "VALUES (:tid, :code, :name, :status)"
                ),
                {
                    "tid": tenant_id,
                    "code": f"VER{suffix[:5].upper()}",
                    "name": f"Verification {suffix}",
                    # Pending needs no plan (ck_tenants_active_requires_plan),
                    # and credential verification does not consult tenant state
                    # — that is gate 2, and it runs above this layer.
                    "status": TenantStatus.PENDING.value,
                },
            )
            yield session, tenant_id
            await session.rollback()
    finally:
        await engine.dispose()


async def _issue(session: AsyncSession, *, tenant_id: uuid.UUID, scopes: list[str] | None = None):
    return await _service().create(
        session,
        tenant_id=tenant_id,
        created_by=None,
        name="Verifier",
        scopes=scopes or ["events:write"],
        expires_in_days=90,
    )


# ------------------------------------------------------------- authentication


async def test_a_valid_secret_authenticates_and_binds_its_own_tenant(tenant_session) -> None:
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id, scopes=["events:write"])

    verified = await _service().verify(session, presented=issued.secret)

    assert verified.tenant_id == tenant_id
    assert verified.used_grace_secret is False
    assert verified.scopes == frozenset({CredentialScope.EVENTS_WRITE})


async def test_the_tenant_comes_from_the_credential_and_not_from_the_caller(
    tenant_session,
) -> None:
    """NR-NF-02, at the one place in the system where it could go wrong.

    `verify` takes a single argument — the presented secret. There is no
    parameter through which a caller could suggest a tenant, which is the
    strongest available form of "never from a path, query or body".
    """
    import inspect

    parameters = inspect.signature(CredentialService.verify).parameters
    assert set(parameters) == {"self", "session", "presented"}


async def test_a_wrong_secret_is_refused(tenant_session) -> None:
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)

    tampered = issued.secret[:-1] + ("A" if issued.secret[-1] != "A" else "B")
    with pytest.raises(AuthError):
        await _service().verify(session, presented=tampered)


async def test_an_unknown_prefix_and_a_wrong_secret_say_the_same_thing(tenant_session) -> None:
    """Otherwise the API is an oracle for which prefixes exist."""
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)

    with pytest.raises(AuthError) as unknown:
        await _service().verify(session, presented="gr_live_ZZZZ.nonsense")
    # A whole new tail rather than one flipped character: a single-character
    # edit can land back on the original when that character was already the
    # replacement, and a test that passes 63 times in 64 is not a test.
    wrong_secret = f"{issued.api_key.visible_prefix}.not-the-secret-for-this-prefix"
    with pytest.raises(AuthError) as wrong:
        await _service().verify(session, presented=wrong_secret)

    assert unknown.value.code == wrong.value.code == "invalid_credentials"


@pytest.mark.parametrize(
    "presented",
    ["", "no-separator", "gr_live_ABCD", "wrong_namespace.secret", "gr_live_ABCD.", "."],
)
async def test_a_malformed_credential_is_refused(tenant_session, presented: str) -> None:
    session, _ = tenant_session
    with pytest.raises(AuthError):
        await _service().verify(session, presented=presented)


async def test_a_revoked_credential_stops_authenticating(tenant_session) -> None:
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    await _service().revoke(session, key_id=issued.api_key.key_id)

    with pytest.raises(AuthError):
        await _service().verify(session, presented=issued.secret)


async def test_an_expired_credential_stops_authenticating(tenant_session) -> None:
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    issued.api_key.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    await session.flush()

    with pytest.raises(AuthError):
        await _service().verify(session, presented=issued.secret)


async def test_a_credential_only_ever_resolves_to_its_own_tenant(tenant_session) -> None:
    """Gate 4 at the verification path, as distinct from the management routes.

    The resolver is the one query in the system that runs before any tenant
    context exists, so it is the one place a prefix could be made to answer for
    the wrong tenant. It answers for exactly one, and it is the owner's.
    """
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)

    resolved = await session.scalar(
        sa.select(sa.func.tenant_lookup.resolve_api_key_prefix(issued.api_key.visible_prefix))
    )
    assert resolved == tenant_id

    verified = await _service().verify(session, presented=issued.secret)
    assert verified.api_key.tenant_id == tenant_id


async def test_the_resolver_cannot_be_made_to_return_a_digest(tenant_session) -> None:
    """It holds column-level SELECT on three columns, and `key_hash` is not one.

    Asserted against `information_schema` rather than by attempting a read,
    because the grant is the thing that has to stay true — a future migration
    widening it would pass any behavioural test written against today's
    function body.
    """
    session, _ = tenant_session
    # Read out of `pg_catalog` rather than `information_schema`, which only
    # shows a grant to a role the *caller* is a member of. `graphrec_app` is a
    # member of nothing, which is the point of it, so the view returns an empty
    # set here and the assertion would pass against any grant at all.
    granted = set(
        (
            await session.scalars(
                sa.text(
                    "SELECT a.attname "
                    "FROM pg_catalog.pg_class AS c "
                    "JOIN pg_catalog.pg_attribute AS a ON a.attrelid = c.oid "
                    "CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) AS acl "
                    "JOIN pg_catalog.pg_roles AS r ON r.oid = acl.grantee "
                    "WHERE c.relname = 'api_keys' AND r.rolname = 'graphrec_lookup' "
                    "AND acl.privilege_type = 'SELECT'"
                )
            )
        ).all()
    )
    assert granted == {"tenant_id", "visible_prefix", "previous_visible_prefix"}
    assert "key_hash" not in granted
    assert "previous_key_hash" not in granted


# ------------------------------------------------------------- rotation grace


async def test_rotation_without_grace_kills_the_old_secret_immediately(tenant_session) -> None:
    """The console's default, and its promise at dc.html L1145."""
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    rotated = await _service().rotate(
        session, key_id=issued.api_key.key_id, scopes=None, grace_seconds=0, reason=None
    )

    with pytest.raises(AuthError):
        await _service().verify(session, presented=issued.secret)
    assert (await _service().verify(session, presented=rotated.secret)).tenant_id == tenant_id


async def test_the_predecessor_still_verifies_during_grace(tenant_session) -> None:
    """BUILD_PROMPT's Phase 3 exit criterion, in one test. ADR 0010."""
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    rotated = await _service().rotate(
        session,
        key_id=issued.api_key.key_id,
        scopes=None,
        grace_seconds=3600,
        reason="scheduled deploy",
    )

    old = await _service().verify(session, presented=issued.secret)
    assert old.tenant_id == tenant_id
    assert old.used_grace_secret is True, "the caller must be told it is on borrowed time"

    new = await _service().verify(session, presented=rotated.secret)
    assert new.used_grace_secret is False


async def test_the_predecessor_stops_the_moment_the_window_lapses(tenant_session) -> None:
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    await _service().rotate(
        session, key_id=issued.api_key.key_id, scopes=None, grace_seconds=3600, reason=None
    )

    # Wind the window back rather than sleeping through it.
    issued.api_key.previous_expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    await session.flush()

    with pytest.raises(AuthError):
        await _service().verify(session, presented=issued.secret)


async def test_the_predecessor_keeps_the_scopes_it_was_rotated_into(tenant_session) -> None:
    """A grace secret is the same credential, so it carries the same authority.

    If it kept its old scopes, revoking a scope would not take effect until the
    window closed, and the window is caller-chosen.
    """
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id, scopes=["events:write", "catalog:write"])
    await _service().rotate(
        session,
        key_id=issued.api_key.key_id,
        scopes=["events:write"],
        grace_seconds=3600,
        reason=None,
    )

    old = await _service().verify(session, presented=issued.secret)
    assert old.scopes == frozenset({CredentialScope.EVENTS_WRITE})


async def test_a_second_rotation_does_not_extend_the_first_window(tenant_session) -> None:
    """Two rotations must never leave three live secrets."""
    session, tenant_id = tenant_session
    first = await _issue(session, tenant_id=tenant_id)
    second = await _service().rotate(
        session, key_id=first.api_key.key_id, scopes=None, grace_seconds=3600, reason=None
    )
    third = await _service().rotate(
        session, key_id=first.api_key.key_id, scopes=None, grace_seconds=0, reason=None
    )

    for dead in (first.secret, second.secret):
        with pytest.raises(AuthError):
            await _service().verify(session, presented=dead)
    assert (await _service().verify(session, presented=third.secret)).tenant_id == tenant_id


async def test_revoking_during_grace_kills_the_predecessor_too(tenant_session) -> None:
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    rotated = await _service().rotate(
        session, key_id=issued.api_key.key_id, scopes=None, grace_seconds=3600, reason=None
    )
    await _service().revoke(session, key_id=issued.api_key.key_id)

    for dead in (issued.secret, rotated.secret):
        with pytest.raises(AuthError):
            await _service().verify(session, presented=dead)


async def test_a_grace_beyond_the_configured_maximum_is_refused(tenant_session) -> None:
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)

    with pytest.raises(ValidationError):
        await _service().rotate(
            session,
            key_id=issued.api_key.key_id,
            scopes=None,
            grace_seconds=86_401,
            reason=None,
        )


async def test_a_revoked_credential_cannot_be_rotated_at_the_service(tenant_session) -> None:
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    await _service().revoke(session, key_id=issued.api_key.key_id)

    with pytest.raises(ConflictError):
        await _service().rotate(
            session, key_id=issued.api_key.key_id, scopes=None, grace_seconds=0, reason=None
        )


# ---------------------------------------------------------------- the cap


async def test_the_credential_cap_reports_both_counts(tenant_session) -> None:
    """The console renders `{used} of {limit}`, so the error has to carry them."""
    session, tenant_id = tenant_session
    service = _service(max_active_per_tenant=2)
    for index in range(2):
        await service.create(
            session,
            tenant_id=tenant_id,
            created_by=None,
            name=f"Capped {index}",
            scopes=["events:write"],
            expires_in_days=90,
        )

    with pytest.raises(LimitError) as excinfo:
        await service.create(
            session,
            tenant_id=tenant_id,
            created_by=None,
            name="One too many",
            scopes=["events:write"],
            expires_in_days=90,
        )
    assert excinfo.value.code == "credential_cap_reached"
    assert excinfo.value.copy_args == {"used": 2, "limit": 2}


async def test_a_revoked_credential_frees_a_slot(tenant_session) -> None:
    session, tenant_id = tenant_session
    service = _service(max_active_per_tenant=1)
    issued = await service.create(
        session,
        tenant_id=tenant_id,
        created_by=None,
        name="Only one",
        scopes=["events:write"],
        expires_in_days=90,
    )
    await service.revoke(session, key_id=issued.api_key.key_id)

    replacement = await service.create(
        session,
        tenant_id=tenant_id,
        created_by=None,
        name="Its replacement",
        scopes=["events:write"],
        expires_in_days=90,
    )
    assert replacement.secret


# -------------------------------------------------------- the secret is opaque


async def test_the_secret_appears_in_no_column_of_the_row(tenant_session) -> None:
    """The strongest statement this suite can make about storage."""
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    await session.flush()

    stored = await session.scalar(sa.select(ApiKey).where(ApiKey.key_id == issued.api_key.key_id))
    assert stored is not None
    rendered = " ".join(str(getattr(stored, column.name)) for column in ApiKey.__table__.columns)

    assert issued.secret not in rendered
    # The random half alone must not appear either.
    assert issued.secret.split(".", 1)[1] not in rendered


async def test_the_issued_credential_never_renders_its_secret(tenant_session) -> None:
    """`repr` is how a secret reaches a log line or a traceback (NR-NF-06)."""
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)

    assert issued.secret not in repr(issued)
    assert "<redacted>" in repr(issued)


# ------------------------------------------------------------ realm boundaries


def test_a_credential_cannot_delegate_a_scope_it_does_not_hold() -> None:
    """The containment property, tested before it has a live call site."""
    from apps.control_api.deps import ForbiddenError, refuse_scope_delegation

    held = frozenset({CredentialScope.EVENTS_WRITE})
    refuse_scope_delegation(held, [CredentialScope.EVENTS_WRITE])

    with pytest.raises(ForbiddenError) as excinfo:
        refuse_scope_delegation(held, [CredentialScope.CATALOG_WRITE])

    assert excinfo.value.code == "insufficient_scope"
    # The refusal must not name the scope that was over-reached.
    assert "catalog" not in str(excinfo.value.copy_args)


def test_a_session_token_is_not_a_credential(api, home_admin) -> None:
    """The realms do not meet, in the direction that matters most.

    A console token accepted as an API credential would make every scope check
    in the system bypassable by anyone holding a login. It is not even
    well-formed as one: `split_presented` refuses it before any lookup.
    """
    from graphrec.auth.api_keys import split_presented

    assert split_presented(home_admin) is None
    # And the credential routes still want the session token, not a credential.
    assert api.get("/v1/api-keys", headers=auth(home_admin)).status_code == 200


# ------------------------------------------------------------ gate 3: scopes


def _principal(api_key: ApiKey, session: AsyncSession, *scopes: CredentialScope):
    from apps.control_api.deps import CredentialPrincipal

    return CredentialPrincipal(
        api_key=api_key,
        scopes=frozenset(scopes),
        session=session,
        used_grace_secret=False,
    )


async def test_a_credential_holding_every_required_scope_passes(tenant_session) -> None:
    from apps.control_api.deps import require_scope

    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id, scopes=["events:write", "catalog:write"])
    principal = _principal(
        issued.api_key, session, CredentialScope.EVENTS_WRITE, CredentialScope.CATALOG_WRITE
    )

    guard = require_scope(CredentialScope.EVENTS_WRITE, CredentialScope.CATALOG_WRITE)
    assert await guard(principal) is principal


async def test_two_declared_scopes_mean_all_of_them_not_any_of_them(tenant_session) -> None:
    """A read-only credential must not reach a route that also writes."""
    from apps.control_api.deps import ForbiddenError, require_scope

    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id, scopes=["recommendations:read"])
    principal = _principal(issued.api_key, session, CredentialScope.RECOMMENDATIONS_READ)

    guard = require_scope(CredentialScope.RECOMMENDATIONS_READ, CredentialScope.EVENTS_WRITE)
    with pytest.raises(ForbiddenError) as excinfo:
        await guard(principal)

    assert excinfo.value.code == "insufficient_scope"


async def test_a_credential_holding_nothing_relevant_is_refused(tenant_session) -> None:
    from apps.control_api.deps import ForbiddenError, require_scope

    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id, scopes=["feedback:write"])
    principal = _principal(issued.api_key, session, CredentialScope.FEEDBACK_WRITE)

    with pytest.raises(ForbiddenError):
        await require_scope(CredentialScope.SUBMISSIONS_READ)(principal)


async def test_a_credential_principal_has_no_role(tenant_session) -> None:
    """The realms carry different things, and this is the one that must not blur.

    A role says which screens a person may open; a scope says which operations a
    program may perform. If a `CredentialPrincipal` grew a `role`, a handler
    written for the session realm would silently accept a credential and treat
    it as whatever that role said.
    """
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    principal = _principal(issued.api_key, session, CredentialScope.EVENTS_WRITE)

    assert not hasattr(principal, "role")
    assert not hasattr(principal, "is_administrator")
    assert principal.tenant_id == tenant_id
    assert principal.has(CredentialScope.EVENTS_WRITE)
    assert not principal.has(CredentialScope.CATALOG_WRITE)


async def test_a_scope_the_database_does_not_recognize_is_not_granted(tenant_session) -> None:
    """Scopes are text in the column, so the model has to be the gate.

    `granted_scopes` drops anything outside the vocabulary rather than passing
    it through. A value that arrived by some other route — a repair script, a
    future migration — must not become authority nobody can name.
    """
    session, tenant_id = tenant_session
    issued = await _issue(session, tenant_id=tenant_id)
    issued.api_key.scopes = ["events:write", "billing:admin"]
    await session.flush()

    assert issued.api_key.granted_scopes() == frozenset({CredentialScope.EVENTS_WRITE})
