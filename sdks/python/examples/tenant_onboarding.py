"""Register a tenant, activate its administrator with the setup token and mint a storefront API key.

python examples/tenant_onboarding.py "Acme Outfitters" owner@acme.example 'a-long-password'
"""

from __future__ import annotations

import sys

from graphrec_sdk import STOREFRONT_KEY_SCOPES, GraphRec


def main(business_name: str, admin_email: str, password: str) -> None:
    with GraphRec(use_env=False) as public:
        tenant = public.tenants.register(name=business_name, admin_email=admin_email)
        print(f"tenant {tenant.id} ({tenant.status}) - next step: {tenant.next_step}")
        if tenant.setup_token is None:
            raise SystemExit(
                "This registration was already submitted, so its one-time setup token is not "
                "returned again. Issue a new one with: docker compose exec api "
                f"python -m scripts.issue_account_setup_token {admin_email}"
            )
        public.auth.setup_password(
            setup_token=tenant.setup_token, password=password, email=admin_email
        )

        # The admin client logs in on demand and renews its 15-minute token automatically.
        admin = public.with_credentials(email=admin_email, password=password)
        plan = admin.subscription.get()
        print(f"plan={plan.plan_code} limits={plan.limits}")

        key = admin.api_keys.create(name="storefront-backend", scopes=STOREFRONT_KEY_SCOPES)
        print("Store this secret now - it is shown only once:")
        print(f"  GRAPHREC_API_KEY={key.secret}")

        usage = admin.usage.get()
        for dimension in usage.dimensions:
            limit = "unlimited" if dimension.limit is None else dimension.limit
            print(f"  {dimension.type:<26} {dimension.used} / {limit} {dimension.unit}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
