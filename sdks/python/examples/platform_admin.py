"""Platform operations: tenants, plans, quota overrides, failures and audit.

The /v1/platform routes authenticate with the server's PLATFORM_ADMIN_TOKEN
(set it in .env; an empty value disables the routes).

    export PLATFORM_ADMIN_TOKEN=...
    python examples/platform_admin.py [tenant-id-to-grant-extra-events]
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from graphrec_sdk import GraphRec, TenantStatus


def main(tenant_id: Optional[str]) -> None:
    with GraphRec(access_token=os.environ["PLATFORM_ADMIN_TOKEN"], use_env=False) as ops:
        print("platform:", ops.platform.status())

        for plan in ops.platform.list_plans():
            print(f"plan {plan.code:<6} {plan.limits}")

        tenants = ops.platform.list_tenants()
        suspended = [t for t in tenants if t.status == TenantStatus.SUSPENDED]
        print(f"{len(tenants)} tenants, {len(suspended)} suspended")

        if tenant_id:
            quota = ops.platform.set_quota_override(
                tenant_id, overrides={"accepted_events": 1_000_000}
            )
            print("effective limits:", quota.limits, "overrides:", quota.overrides)

        for failure in ops.platform.list_failures()[:10]:
            print(
                f"{failure.occurred_at:%Y-%m-%d %H:%M} {failure.severity:<7} {failure.event_type}"
            )
        for record in ops.platform.list_audit_logs()[:10]:
            print(f"{record.occurred_at:%Y-%m-%d %H:%M} {record.action_type} -> {record.outcome}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
