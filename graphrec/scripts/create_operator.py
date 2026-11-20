"""Create a platform operator from the command line (D-04 bootstrap).

    docker compose run --rm api python -m scripts.create_operator \
        --email ops@example.com --name "Ops Lead" --roles operator_admin,platform,plan_management,monitoring,audit

The password is read from the OPERATOR_PASSWORD environment variable or prompted
for, never taken from the command line (it would land in shell history).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from uuid import uuid4

from sqlalchemy import text

from graphrec_core.auth.passwords import hash_password
from graphrec_core.auth.platform import ROLES
from graphrec_core.database.session import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--roles", default=",".join(ROLES), help=f"comma-separated subset of {', '.join(ROLES)}")
    args = parser.parse_args()
    roles = sorted({r.strip() for r in args.roles.split(",") if r.strip()})
    unknown = set(roles) - set(ROLES)
    if unknown or not roles:
        print(f"Unknown or missing roles: {sorted(unknown)}", file=sys.stderr)
        return 2
    password = os.environ.get("OPERATOR_PASSWORD") or getpass.getpass("Operator password (12+ characters): ")
    if len(password) < 12:
        print("The password must be at least 12 characters.", file=sys.stderr)
        return 2
    with SessionLocal() as db, db.begin():
        db.execute(text("INSERT INTO platform_operators (id, email, display_name, password_hash, roles) "
                        "VALUES (:id, :email, :name, :hash, :roles)"),
                   {"id": uuid4(), "email": args.email, "name": args.name, "hash": hash_password(password), "roles": roles})
    print(f"Operator {args.email} created with roles: {', '.join(roles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
