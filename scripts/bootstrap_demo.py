"""Create the demo tenant, its administrators and a platform operator.

§24 Operations asks for a "demo account bootstrap script"; the `DEMO_*` settings
have existed since Phase 1 and until now nothing read them. A setting nobody
reads is worse than a missing one — it reads like a feature in `.env.example`.

**Idempotent, and by lookup rather than by exception.** Run it twice and the
second run prints four `exists` lines and changes nothing. That matters more
than it sounds: the natural way to write this is to catch the unique-violation,
which also swallows the violation that means something else went wrong.

**It refuses to run on a deployed host with the default password.** The
credential in `.env.example` is in the repository, so seeding it onto a public
host would be publishing an administrator. `--force` exists for the operator who
has genuinely changed it and still wants an obvious demo account; it is a
decision somebody has to type.

In production that refusal is belt and braces — `Settings` will not even
construct while carrying a shipped default. Staging is the environment the
validator does not cover and this guard does.

Three roles, three connections, deliberately:

* the *app* role registers the tenant, because `register_tenant` binds the
  tenant it is about to create and the `WITH CHECK` clause on `tenants` is what
  makes that safe. Running it as the owner would work and would prove nothing;
* the *platform* role activates the tenant and creates the operator, because
  those are platform decisions and the platform role is the one that holds the
  grants for them (SRS §5.2.1);
* neither role can do the other's job, which is the property this script would
  fail to start if somebody broke.

Usage:
    python scripts/bootstrap_demo.py [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import secrets
import sys
from typing import TYPE_CHECKING

import sqlalchemy as sa

from graphrec.auth.passwords import hash_password
from graphrec.auth.tokens import TokenService
from graphrec.common.config import Environment, get_settings
from graphrec.common.enums import PlatformPermission, TenantRole, TenantStatus, UserStatus
from graphrec.common.ids import uuid7
from graphrec.common.logging import configure_logging
from graphrec.db.engine import create_platform_engine, create_sessionmaker, create_worker_engine
from graphrec.db.models import (
    PlatformUser,
    PlatformUserPermission,
    PricingPlan,
    Tenant,
    TenantUser,
)
from graphrec.db.tenant_context import bind_tenant
from graphrec.domain.identity.service import IdentityService
from graphrec.domain.platform.tenants import assign_plan, change_status

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

#: The default that ships in `.env.example`. Compared against, never used.
PUBLISHED_DEFAULT = "local-demo-password-change-me"

DEMO_TENANT_CODE = "demo"
DEMO_PLAN_CODE = "STARTER"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the demo tenant and operator.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="seed even in production with the published default password",
    )
    return parser.parse_args(argv)


def _say(action: str, what: str) -> None:
    print(f"  {action:<8} {what}")


async def _tenant_by_name(session: AsyncSession, name: str) -> Tenant | None:
    found: Tenant | None = await session.scalar(sa.select(Tenant).where(Tenant.tenant_name == name))
    return found


async def _seed_tenant(sessionmaker, settings) -> tuple[bool, str]:
    """Register the tenant and its first administrator, as the app role.

    Returns whether anything was created, and the tenant code — which the
    caller prints, because a demo nobody can find the sign-in code for is a
    demo nobody can sign in to.
    """
    platform_engine = create_platform_engine(settings)
    platform_sessionmaker = create_sessionmaker(platform_engine)
    try:
        async with platform_sessionmaker() as session:
            existing = await _tenant_by_name(session, settings.demo_tenant_name)
            if existing is not None:
                _say("exists", f"tenant {existing.tenant_name!r} ({existing.tenant_code})")
                return False, existing.tenant_code
    finally:
        await platform_engine.dispose()

    # The real `TokenService`, built the way `create_app` builds it. Nothing
    # here mints a token — `register_tenant` does not — but constructing a
    # working one means this script fails loudly on a host whose signing keys
    # are missing, which is a host where the demo account could not sign in
    # anyway.
    service = IdentityService(
        TokenService(
            private_key_path=settings.jwt_private_key_path,
            public_key_path=settings.jwt_public_key_path,
            key_id=settings.jwt_key_id,
            issuer=settings.jwt_issuer,
            access_ttl_seconds=settings.access_token_ttl_seconds,
            refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
        )
    )
    async with sessionmaker() as session, session.begin():
        await service.register_tenant(
            session,
            tenant_name=settings.demo_tenant_name,
            tenant_code=DEMO_TENANT_CODE,
            email=settings.demo_registration_email,
            password=settings.demo_login_password.get_secret_value(),
            plan_id=None,
        )
    _say("created", f"tenant {settings.demo_tenant_name!r} ({DEMO_TENANT_CODE})")
    return True, DEMO_TENANT_CODE


async def _activate(session: AsyncSession, settings, *, operator_id: uuid.UUID) -> None:
    """A pending tenant cannot do anything, which is correct and useless here.

    **The plan comes first, and that ordering is a constraint, not a habit.**
    `ck_tenants_active_requires_plan` refuses an active tenant with no plan, so
    an activation written before the subscription fails at the database rather
    than at a review — which is how this script was written the first time.

    `assign_plan` and `change_status` are the same two functions the platform
    console calls, reason and all, so the demo tenant carries a real
    subscription row and a real activation row rather than two `UPDATE`s nobody
    can explain later.
    """
    tenant = await _tenant_by_name(session, settings.demo_tenant_name)
    if tenant is None:
        msg = "the demo tenant was not visible to the platform role after creation"
        raise SystemExit(msg)

    if tenant.plan_id is None:
        # Starter, because it is what a real tenant lands on and because the
        # quota screens are only interesting against limits somebody could hit.
        plan = await session.scalar(
            sa.select(PricingPlan).where(PricingPlan.plan_code == DEMO_PLAN_CODE)
        )
        if plan is None:
            msg = f"no {DEMO_PLAN_CODE!r} plan — run the migrations first"
            raise SystemExit(msg)
        await assign_plan(
            session,
            tenant,
            plan=plan,
            assigned_by=operator_id,
            reason="Demo bootstrap (scripts/bootstrap_demo.py).",
        )
        _say("plan", f"{plan.plan_code} assigned")
    else:
        _say("exists", "tenant already has a plan")

    if tenant.status == TenantStatus.ACTIVE.value:
        _say("exists", "tenant is already active")
        return
    await change_status(
        session,
        tenant,
        status=TenantStatus.ACTIVE,
        reason="Demo bootstrap (scripts/bootstrap_demo.py).",
        now=dt.datetime.now(dt.UTC),
    )
    _say("active", f"tenant {tenant.tenant_name!r}")


async def _seed_console_administrator(sessionmaker, settings) -> None:
    """The account a demo is signed in as, alongside the registering owner.

    Two administrators rather than one because `DEMO_REGISTRATION_EMAIL` and
    `DEMO_LOGIN_EMAIL` are two settings, and collapsing them would leave one of
    them still unread.
    """
    email = settings.demo_login_email.strip().lower()
    platform_engine = create_platform_engine(settings)
    platform_sessionmaker = create_sessionmaker(platform_engine)
    try:
        async with platform_sessionmaker() as session:
            tenant = await _tenant_by_name(session, settings.demo_tenant_name)
            if tenant is None:
                msg = "no demo tenant to add an administrator to"
                raise SystemExit(msg)
            tenant_id = tenant.tenant_id
    finally:
        await platform_engine.dispose()

    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, tenant_id)
        existing = await session.scalar(sa.select(TenantUser).where(TenantUser.email == email))
        if existing is not None:
            _say("exists", f"console administrator {email}")
            return
        session.add(
            TenantUser(
                tenant_user_id=uuid7(),
                tenant_id=tenant_id,
                email=email,
                display_name=email.split("@", 1)[0],
                credential_digest=hash_password(settings.demo_login_password.get_secret_value()),
                role=TenantRole.TENANT_ADMINISTRATOR.value,
                status=UserStatus.ACTIVE.value,
            )
        )
    _say("created", f"console administrator {email}")


async def _seed_operator(session: AsyncSession, settings) -> uuid.UUID:
    """The platform realm's account, with all five permissions.

    All five, because a demo of the platform console with `audit` withheld is a
    demo of an empty page. This is the account the `--force` guard is about.
    """
    email = settings.demo_login_email.strip().lower()
    existing = await session.scalar(sa.select(PlatformUser).where(PlatformUser.email == email))
    if existing is not None:
        _say("exists", f"platform operator {email}")
        return existing.platform_user_id
    operator = PlatformUser(
        platform_user_id=uuid7(),
        email=email,
        display_name="Demo operator",
        credential_digest=hash_password(settings.demo_login_password.get_secret_value()),
        status=UserStatus.ACTIVE.value,
    )
    session.add(operator)
    await session.flush()
    for permission in PlatformPermission:
        session.add(
            PlatformUserPermission(
                platform_user_id=operator.platform_user_id,
                permission=permission.value,
                granted_by=None,
            )
        )
    _say("created", f"platform operator {email} with all five permissions")
    return operator.platform_user_id


async def run(force: bool) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    password = settings.demo_login_password.get_secret_value()
    # `compare_digest`, not `==`. The comparison is not a secret check, but a
    # constant-time habit costs nothing and the alternative teaches the wrong
    # reflex to whoever copies this file.
    # Staging is this guard's real jurisdiction. `Settings` already refuses to
    # construct at all in *production* while carrying a shipped default (see
    # `_production_requires_real_secrets`), so the script could never reach this
    # line there — but staging is a deployed environment that validator does not
    # cover, and a staging host is reachable from the internet often enough.
    if (
        settings.environment not in {Environment.LOCAL, Environment.CI}
        and secrets.compare_digest(password, PUBLISHED_DEFAULT)
        and not force
    ):
        print(
            f"refusing: environment is {settings.environment!r} and DEMO_LOGIN_PASSWORD is "
            "the value published in .env.example. Change it, or pass --force.",
            file=sys.stderr,
        )
        return 1

    print("demo bootstrap")
    app_engine = create_worker_engine(settings)
    app_sessionmaker = create_sessionmaker(app_engine)
    try:
        _, tenant_code = await _seed_tenant(app_sessionmaker, settings)
        await _seed_console_administrator(app_sessionmaker, settings)
    finally:
        await app_engine.dispose()

    platform_engine = create_platform_engine(settings)
    platform_sessionmaker = create_sessionmaker(platform_engine)
    try:
        async with platform_sessionmaker() as session, session.begin():
            # The operator first: `assign_plan` records who assigned it, and a
            # subscription attributed to nobody is one nobody can question.
            operator_id = await _seed_operator(session, settings)
            await _activate(session, settings, operator_id=operator_id)
    finally:
        await platform_engine.dispose()

    print()
    print(f"  sign in at /login with tenant code {tenant_code!r} as {settings.demo_login_email}")
    print(f"  sign in at /admin/login as {settings.demo_login_email}")
    print("  the password is DEMO_LOGIN_PASSWORD")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(run(force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
