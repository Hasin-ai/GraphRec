"""The platform realm's reads and writes. Tenant is a filter, never a scope.

Every function here runs on the platform connection — `graphrec_platform`, a
role that holds grants on the twelve tables `/admin/*` renders and on nothing
else. None of them calls `bind_tenant`, and none of them takes a session it
expects to be bound: `app.tenant_id` is unset for the whole realm, so a query
that forgot a `WHERE tenant_id =` returns every tenant rather than none. That is
the inversion this package exists to hold, and it is why the boundary is a role
with a short grant list rather than a promise about how the queries are written.

The four modules divide by what a permission grants:

* `tenants` — the estate: who exists, what state they are in, and the two writes
  (`:status`, `:assign-plan`) that change it. `platform permission`, except the
  plan write.
* `plans` — the price list, which no tenant may edit and which a plan-management
  operator may. Closing one is reversible; the limits on one are not versioned.
* `usage` — aggregate quantities across tenants. Reads `monthly_usage_aggregates`
  and nothing else, because the ledger under it carries per-event rows that are
  the tenant's own business (L1438).
* `status` — the installation's health, assembled from five independent readings
  that fail independently. Its contract is that an unmeasurable quantity is
  reported as a gap and never as a zero.
"""

from graphrec.domain.platform.plans import (
    PlanDetail,
    PlanSummary,
    close_plan,
    create_plan,
    list_plans,
    plan_detail,
    reopen_plan,
    require_plan,
    update_plan,
)
from graphrec.domain.platform.status import (
    PlatformStatus,
    QueueDepth,
    ReplicaCount,
    TenantWorkload,
    platform_status,
)
from graphrec.domain.platform.tenants import (
    PlanSection,
    Section,
    StatusSection,
    TenantDetail,
    TenantPage,
    TenantSummary,
    UsageSection,
    assign_plan,
    change_status,
    grant_override,
    list_tenants,
    require_tenant,
    tenant_detail,
)
from graphrec.domain.platform.usage import PlatformUsageRow, cross_tenant_usage, tenant_usage

__all__ = [
    "PlanDetail",
    "PlanSummary",
    "PlatformStatus",
    "PlatformUsageRow",
    "PlanSection",
    "QueueDepth",
    "ReplicaCount",
    "Section",
    "StatusSection",
    "TenantDetail",
    "TenantPage",
    "TenantSummary",
    "TenantWorkload",
    "UsageSection",
    "assign_plan",
    "change_status",
    "close_plan",
    "create_plan",
    "cross_tenant_usage",
    "grant_override",
    "list_plans",
    "list_tenants",
    "plan_detail",
    "platform_status",
    "reopen_plan",
    "require_plan",
    "require_tenant",
    "tenant_detail",
    "tenant_usage",
    "update_plan",
]
