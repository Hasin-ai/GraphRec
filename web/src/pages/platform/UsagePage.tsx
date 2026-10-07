import { Fragment } from "react";
import { Link } from "react-router-dom";
import { platform } from "../../api";
import type { PlatformTenantUsage } from "../../api/types";
import { useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { fmtNumber, humanize } from "../../lib/format";
import { Page } from "../../ui/Page";
import { Cell, DataTable, ErrorBanner, FilterBar, Footnote, Skeleton, Tag } from "../../ui/primitives";

const SHOWN = ["stored_products", "accepted_events", "recommendation_requests", "training_jobs", "active_model_versions"];

function peak(tenant: PlatformTenantUsage): number {
  return Math.max(0, ...tenant.dimensions.filter(d => d.measured && d.limit).map(d => d.used / (d.limit as number)));
}

function cell(tenant: PlatformTenantUsage, type: string) {
  if (tenant.unavailable) return <Cell muted>Unavailable</Cell>;
  const d = tenant.dimensions.find(x => x.type === type);
  if (!d) return <Cell muted>—</Cell>;
  if (!d.measured) return <Cell muted>Not measured</Cell>;
  const ratio = d.limit ? d.used / d.limit : 0;
  return <Cell mono>{d.limit !== null ? <Tag tone={ratio >= 1 ? "danger" : ratio >= 0.8 ? "warn" : "neu"}>{fmtNumber(d.used)} / {fmtNumber(d.limit)}</Tag> : `${fmtNumber(d.used)} / no limit`}</Cell>;
}

/** UC-29: usage across every tenant, worst first. Aggregates only. */
export function PlatformUsagePage() {
  const usage = useResource(() => platform.listUsage(), []);
  const [view, setView] = useQueryState("show", "all tenants");
  const rows = (usage.data?.items ?? []).filter(t => view === "all tenants" || (view === "at or near a limit" ? peak(t) >= 0.8 : t.unavailable))
    .sort((a, b) => Number(b.unavailable) - Number(a.unavailable) || peak(b) - peak(a));
  return <Page crumbs={[{ label: "Platform", to: "/admin/status" }, { label: "Usage" }]} kicker="Monitoring permission" title="Usage across tenants"
    subtitle="Current-period usage against each tenant's plan limits. Tenants at 80% or more of a limit are highlighted." actions={[{ label: "Refresh", onClick: () => void usage.reload(), disabled: usage.loading }]}>
    {usage.error ? <ErrorBanner error={usage.error} onRetry={usage.reload} /> : null}
    <FilterBar filters={[{ id: "show", label: "Show", value: view, onChange: setView, options: ["all tenants", "at or near a limit", "unavailable"] }]} onClear={() => setView("all tenants")} />
    {!usage.data ? usage.loading ? <Skeleton /> : null : <DataTable minWidth={1100}
      columns={["Tenant", "Plan", ...SHOWN.map(humanize)]}
      rows={rows.map(t => <tr key={t.tenant_id}>
        <Cell sub={humanize(t.status)}><Link to={`/admin/tenants/${t.tenant_id}`}>{t.name}</Link></Cell>
        <Cell>{t.plan_code ? humanize(t.plan_code) : "—"}</Cell>
        {SHOWN.map(type => <Fragment key={type}>{cell(t, type)}</Fragment>)}
      </tr>)}
      count={`${rows.length} of ${usage.data.items.length} tenants`} empty={{ title: "No tenants match", body: "Widen the filter." }} />}
    <Footnote>"Unavailable" means the usage could not be read for that tenant; it is never shown as zero.</Footnote>
  </Page>;
}
