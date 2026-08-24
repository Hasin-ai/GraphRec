#!/usr/bin/env python3
"""Mint a recovery proof for a tenant user and print it. No mail transport needed.

`docs/BUILD_PROMPT.md` L90 asks whether SMTP exists and says what to do when it
does not: *"build an admin CLI that prints the token and say so in your report."*
This is that CLI. It is the supported way for an operator to answer a support
ticket that says "I have lost access to my account", and it is the only path by
which a recovery proof reaches a human without passing through a log file.

    python scripts/recovery_token.py --tenant-code NORTHGATE --email ada@northgate.example

It mints exactly what `POST /v1/auth/recovery` mints, through the same
`IdentityService.request_recovery`, so the proof it prints is consumed by the
ordinary `/recover/confirm` flow and every lifecycle rule applies unchanged —
including the revocation of any proof already outstanding for that account.

Two differences from the HTTP endpoint, both intentional:

* It **says whether the account was found.** An operator running this has
  already authenticated to a shell on the control plane; the non-disclosure the
  endpoint practises is aimed at anonymous callers on the internet and would
  only make this tool useless.
* It **prints to stdout**, not to the logger. A proof in a terminal scrollback
  is a smaller problem than a proof in a shipped log stream.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import sqlalchemy as sa

from graphrec.auth.tokens import TokenService
from graphrec.common.config import Settings
from graphrec.db.engine import create_app_engine, create_sessionmaker
from graphrec.domain.identity import IdentityService


async def _mint(settings: Settings, tenant_code: str, email: str) -> int:
    engine = create_app_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    service = IdentityService(
        TokenService(settings), recovery_ttl_seconds=settings.recovery_ttl_seconds
    )
    try:
        async with sessionmaker() as session, session.begin():
            tenant_id = await session.scalar(
                sa.select(sa.func.tenant_lookup.resolve_tenant_code(tenant_code))
            )
            if tenant_id is None:
                print(f"No tenant has the code {tenant_code!r}.", file=sys.stderr)
                return 2
            issued = await service.request_recovery(session, tenant_id=tenant_id, email=email)
            if issued is None:
                print(
                    f"No account for {email!r} in {tenant_code!r} that is able to sign in. "
                    "An invited, locked or disabled account cannot be recovered — "
                    "reinstate it first.",
                    file=sys.stderr,
                )
                return 3
            # Read inside the transaction; the objects are expired after commit.
            proof, expires_at, display = issued.token, issued.expires_at, issued.user.email
    finally:
        await engine.dispose()

    print(f"Recovery proof for {display}:")
    print(f"  {proof}")
    print(f"Valid until {expires_at.isoformat()}. Single use.")
    print("Give it to the account holder over a channel you trust, and to nobody else.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant-code", required=True, help="The tenant's code, e.g. NORTHGATE")
    parser.add_argument("--email", required=True, help="The account identifier")
    args = parser.parse_args(argv)
    return asyncio.run(_mint(Settings(), args.tenant_code, args.email))


if __name__ == "__main__":
    raise SystemExit(main())
