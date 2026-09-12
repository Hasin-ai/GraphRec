"""Create a fresh GraphRec tenant for the demo and write the keys into .env.

    python scripts/bootstrap_tenant.py --base-url http://localhost:8010

Registers a tenant, activates its administrator with the one-time setup token,
creates two API keys (a minimal storefront key and a seed key with training and
model scopes) and writes GRAPHREC_* into apps/demo-storefront/.env. Nothing is
printed that is not also written to .env, and the file is only ever updated -
other variables in it are kept.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

from _common import PACKAGE_DIR, load_env, step

from graphrec_sdk import STOREFRONT_KEY_SCOPES, GraphRec

#: Everything scripts/seed.py and verify_personalization.py need (the server caps a key at 12 scopes).
SEED_KEY_SCOPES = [
    "catalog:read", "catalog:write", "events:read", "events:write",
    "training:read", "training:write", "models:read", "models:write", "models:deploy",
    "recommendations:read",
]


def write_env(path: Path, updates: dict) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else (PACKAGE_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=None, help="GraphRec API origin (default: GRAPHREC_BASE_URL or http://localhost:8010)")
    parser.add_argument("--name", default="Facet Demo Store")
    parser.add_argument("--email", default=None, help="administrator email (default: a random facet-demo-* address)")
    parser.add_argument("--env-file", default=str(PACKAGE_DIR / ".env"))
    args = parser.parse_args()

    import os

    base_url = args.base_url or os.environ.get("GRAPHREC_BASE_URL") or "http://localhost:8010"
    suffix = secrets.token_hex(3)
    email = args.email or f"facet-demo-{suffix}@example.org"
    password = "facet-" + secrets.token_urlsafe(18)

    public = GraphRec(base_url=base_url, use_env=False)
    step(f"health @ {base_url}")
    print(public.health())

    step("register tenant")
    tenant = public.tenants.register(name=f"{args.name} {suffix}", admin_email=email)
    if not tenant.setup_token:
        raise SystemExit("Registration replayed without a setup token; choose a different --email.")
    public.auth.setup_password(setup_token=tenant.setup_token, password=password, email=email)
    print(f"tenant {tenant.id} - admin {email}")

    admin = public.with_credentials(email=email, password=password)
    step("API keys")
    storefront = admin.api_keys.create(name="facet-storefront", scopes=STOREFRONT_KEY_SCOPES)
    seed = admin.api_keys.create(name="facet-seed", scopes=SEED_KEY_SCOPES)
    print(f"storefront key {storefront.prefix}... scopes={list(storefront.scopes)}")
    print(f"seed key       {seed.prefix}... scopes={list(seed.scopes)}")

    env_path = Path(args.env_file)
    write_env(
        env_path,
        {
            "GRAPHREC_BASE_URL": base_url,
            "GRAPHREC_API_KEY": storefront.secret,
            "GRAPHREC_SEED_API_KEY": seed.secret,
            "DEMO_ADMIN_EMAIL": email,
            "DEMO_ADMIN_PASSWORD": password,
            "DEMO_TENANT_ID": str(tenant.id),
        },
    )
    step("done")
    print(f"Wrote credentials to {env_path}. Next: python scripts/seed.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
