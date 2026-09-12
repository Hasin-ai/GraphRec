"""Issue a fresh one-time account setup token for an invited tenant user.

Use this when the registrant lost the ``setup_token`` from the original
registration response (replays never return it) or the token expired:

    docker compose exec api python -m scripts.issue_account_setup_token admin@example.org

Pass ``--tenant-id`` when the same address is invited in more than one tenant.
Issuing a token revokes any older unused tokens for that user. The token is
printed once and is not recoverable afterwards; only its hash is stored.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text

from graphrec_core.auth.setup_tokens import issue_setup_token, revoke_open_setup_tokens
from graphrec_core.database.models import AuditLog
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.settings import get_settings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Issue a one-time account setup token for an invited tenant user."
    )
    parser.add_argument("email", help="Email address of the invited user")
    parser.add_argument("--tenant-id", type=UUID, default=None, help="Tenant to pick")
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help="Token lifetime (defaults to ACCOUNT_SETUP_TOKEN_TTL_SECONDS)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    ttl_seconds = args.ttl_seconds or settings.account_setup_token_ttl_seconds
    if not 300 <= ttl_seconds <= 604_800:
        print("--ttl-seconds must be between 300 and 604800", file=sys.stderr)
        return 2

    with SessionLocal() as session, session.begin():
        rows = (
            session.execute(
                text(
                    "SELECT user_id, tenant_id, credential_digest, user_status, tenant_status "
                    "FROM resolve_login_identities(:email)"
                ),
                {"email": args.email},
            )
            .mappings()
            .all()
        )
        if args.tenant_id is not None:
            rows = [row for row in rows if row["tenant_id"] == args.tenant_id]
        if not rows:
            print("No user with that email address was found", file=sys.stderr)
            return 1
        if len(rows) > 1:
            tenants = ", ".join(str(row["tenant_id"]) for row in rows)
            print(f"Email exists in several tenants; pass --tenant-id ({tenants})", file=sys.stderr)
            return 1

        identity = rows[0]
        if identity["user_status"] != "invited" or identity["credential_digest"] is not None:
            print(
                "This account is already set up; setup tokens only activate invited accounts",
                file=sys.stderr,
            )
            return 1
        if identity["tenant_status"] != "active":
            print("The tenant is not active", file=sys.stderr)
            return 1

        now = datetime.now(timezone.utc)
        tenant_id: UUID = identity["tenant_id"]
        user_id: UUID = identity["user_id"]
        set_local_tenant(session, tenant_id)
        revoked = revoke_open_setup_tokens(session, tenant_id=tenant_id, user_id=user_id, now=now)
        token, expires_at = issue_setup_token(
            session, tenant_id=tenant_id, user_id=user_id, ttl_seconds=ttl_seconds, now=now
        )
        session.add(
            AuditLog(
                id=uuid4(),
                tenant_id=tenant_id,
                actor_type="system_process",
                actor_reference=None,
                action_type="account_setup_token_issued",
                resource_type="tenant_user",
                resource_reference=user_id,
                outcome="succeeded",
                correlation_reference=uuid4(),
                redacted_details={"revoked_tokens": revoked, "ttl_seconds": ttl_seconds},
                occurred_at=now,
            )
        )

    print(f"tenant_id:  {tenant_id}")
    print(f"expires_at: {expires_at.isoformat()}")
    print(f"setup_token: {token}")
    print(f"console:    /auth/setup#token={token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
