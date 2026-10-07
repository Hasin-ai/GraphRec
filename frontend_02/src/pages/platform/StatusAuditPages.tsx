import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { platform } from "../../api";
import type { PlatformAudit } from "../../api/types";
import { useClearQuery, useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { fmtDateTime, relativeSeconds, shortId } from "../../lib/format";
import { Page } from "../../ui/Page";
import { Badge, Cell, DataTable, DefinitionList, ErrorBanner, FilterBar, Footnote, Skeleton, Stats, Tabs } from "../../ui/primitives";

export function PlatformStatusPage() {
  const status = useResource(() => platform.status(), []);
  const tenants = useResource(() => platform.listTenants(), []);
  const failures = useResource(() => platform.listFailures(), []);
  const s = status.data;
  const activeTenants = tenants.data?.items.filter((t) => t.status === "active").length ?? 0;
  const dayAgo = Date.now() - 86_400_000;
  const recentFailures = failures.data?.items.filter((f) => new Date(f.occurred_at).getTime() >= dayAgo).length;

  return (
    <Page
      crumbs={[{ label: "Platform", to: "/admin/status" }, { label: "Platform Status" }]}
      kicker="Monitoring access"
      title="Platform Status"
      badge={s ? <Badge group="platform" value={s.status} /> : undefined}
      subtitle="Shared service health across the platform. Components that are not deployed are identified as such, never as healthy."
      updated={status.loadedAt ? `updated ${relativeSeconds(status.loadedAt)}` : undefined}
      actions={[{ label: "Refresh", onClick: () => { void status.reload(); void tenants.reload(); void failures.reload(); } }]}
    >
      {status.error ? <ErrorBanner error={status.error} onRetry={status.reload} /> : null}
      {!s && status.loading ? (
        <Skeleton />
      ) : s ? (
        <>
          <DefinitionList
            items={[
              { label: "Overall", badge: <Badge group="platform" value={s.status} /> },
              { label: "Reported at", value: fmtDateTime(s.timestamp), mono: true },
              { label: "API cluster", badge: <Badge group="platform" value={s.api_cluster} /> },
              { label: "Database", badge: <Badge group="platform" value={s.database} /> },
              { label: "Worker pool", badge: <Badge group="platform" value={s.worker_pool} /> },
              ...(s.rate_limiter ? [
                { label: "Rate-limit store (Redis)", badge: <Badge group="platform" value={s.rate_limiter.status} /> },
                { label: "Admitted without the shared store", value: String(s.rate_limiter.fail_open_total) },
              ] : []),
              ...(s.deployments ? [
                { label: "Ready local capacity", value: `${s.deployments.ready_capacity} of ${s.deployments.desired_capacity}` },
                { label: "Degraded tenants", value: String(s.deployments.degraded_tenants) },
              ] : []),
            ]}
          />
        </>
      ) : null}
      {tenants.error ? <ErrorBanner error={tenants.error} title="Tenant counts unavailable" onRetry={tenants.reload} /> : null}
      {failures.error ? <ErrorBanner error={failures.error} title="Recent failures unavailable" onRetry={failures.reload} /> : null}
      <Stats items={[
        { label: "Active tenants", value: tenants.data ? String(activeTenants) : tenants.loading ? "Loading…" : "Unavailable", note: tenants.data ? `of ${tenants.data.items.length} accounts` : undefined },
        { label: "Recent failures", value: recentFailures === undefined ? failures.loading ? "Loading…" : "Unavailable" : String(recentFailures), note: "Last 24 hours within the 50 latest records" },
      ]} />
      <Footnote>Training runs in a separate worker. Capacity counts reflect the most recent local activation checks, not continuous health probing.</Footnote>
    </Page>
  );
}

type Tab = "Failures" | "Audit records";

export function PlatformAuditPage() {
  const clearQuery = useClearQuery();
  const [tabParam, setTab] = useQueryState("view", "Failures");
  const tab: Tab = tabParam === "Audit records" ? "Audit records" : "Failures";
  const failures = useResource(() => platform.listFailures(), []);
  const [severity, setSeverity] = useQueryState("severity", "all severities");
  const [action, setAction] = useQueryState("action", "all action types");
  const [tenant, setTenant] = useQueryState("tenant", "");
  // UC-31: a full tenant id and an action type filter on the server; a partial id narrows the loaded page.
  const exactTenant = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(tenant.trim()) ? tenant.trim() : undefined;
  const serverAction = action === "all action types" ? undefined : action;
  const audit = useResource(() => platform.listAudit({ tenant_id: exactTenant, action: serverAction, limit: 200 }), [exactTenant, serverAction]);
  const [older, setOlder] = useState<{ items: PlatformAudit[]; next: string | null } | null>(null);
  useEffect(() => setOlder(null), [exactTenant, serverAction]);
  const [loadingOlder, setLoadingOlder] = useState(false);

  const failureList = (failures.data?.items ?? []).filter((f) => severity === "all severities" || f.severity === severity);
  const auditItems = [...(audit.data?.items ?? []), ...(older?.items ?? [])];
  const nextBefore = older ? older.next : audit.data?.next_before ?? null;
  const actionTypes = Array.from(new Set([...auditItems.map((a) => a.action_type), ...(serverAction ? [serverAction] : [])])).sort();
  async function loadOlder() {
    if (!nextBefore) return;
    setLoadingOlder(true);
    try {
      const page = await platform.listAudit({ tenant_id: exactTenant, action: serverAction, before: nextBefore, limit: 200 });
      setOlder(previous => ({ items: [...(previous?.items ?? []), ...page.items], next: page.next_before }));
    } finally { setLoadingOlder(false); }
  }
  const auditList = auditItems.filter((a) => (action === "all action types" || a.action_type === action) && (!tenant.trim() || a.tenant_id?.startsWith(tenant.trim())));

  return (
    <Page crumbs={[{ label: "Platform", to: "/admin/status" }, { label: "Failures & Audit", to: "/admin/audit" }, { label: tab }]} kicker="Audit permission" title="Failures & Audit" subtitle={tab === "Failures" ? "Redacted security and failure events across the platform. Details are sanitized before they are stored." : "Immutable, append-only history. Sensitive details stay redacted."}>
      <Tabs tabs={["Failures", "Audit records"] as Tab[]} value={tab} onChange={setTab} />
      <div className="stack" id="view-panel" role="tabpanel" aria-labelledby={`tab-${tab.replaceAll(" ", "-")}`}>
      {tab === "Failures" ? (
        <>
          {failures.error ? <ErrorBanner error={failures.error} onRetry={failures.reload} /> : null}
          <FilterBar filters={[{ id: "sev", label: "Severity", value: severity, onChange: setSeverity, options: ["all severities", ...Array.from(new Set((failures.data?.items ?? []).map((f) => f.severity))).sort()] }]} onClear={() => setSeverity("all severities")} />
          {!failures.data ? (failures.loading ? <Skeleton /> : null) : (
            <DataTable
              minWidth={850}
              columns={["Occurred at", "Severity", "Event type", "Detail", "Tenant"]}
              rows={failureList.map((f) => (
                <tr key={f.id}>
                  <Cell mono>{fmtDateTime(f.occurred_at)}</Cell>
                  <td>
                    <Badge group="sev" value={f.severity} />
                  </td>
                  <Cell mono>{f.event_type}</Cell>
                  <Cell muted>
                    {Object.entries(f.sanitized_detail)
                      .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
                      .join(" · ") || "—"}
                  </Cell>
                  <Cell mono muted>
                    {f.tenant_id ? <Link to={`/admin/tenants/${f.tenant_id}`}>{shortId(f.tenant_id)}</Link> : "redacted"}
                  </Cell>
                </tr>
              ))}
              count={`${failureList.length} of the ${failures.data?.items.length ?? 0} most recent`}
              empty={{ title: "No failures match this filter", body: "Widen the severity filter." }}
            />
          )}
        </>
      ) : (
        <>
          {audit.error ? <ErrorBanner error={audit.error} onRetry={audit.reload} /> : null}
          <FilterBar
            filters={[
              { id: "action", label: "Action type", value: action, onChange: setAction, options: ["all action types", ...actionTypes] },
              { id: "tenant", label: "Tenant id", value: tenant, onChange: setTenant, placeholder: "starts with…" },
            ]}
            onClear={() => clearQuery('action', 'tenant')}
          />
          {!audit.data ? (audit.loading ? <Skeleton /> : null) : (
            <DataTable
              minWidth={850}
              columns={["Occurred at", "Actor", "Action type", "Resource type", "Outcome", "Reason", "Tenant"]}
              rows={auditList.map((a) => (
                <tr key={a.id}>
                  <Cell mono>{fmtDateTime(a.occurred_at)}</Cell>
                  <Cell mono>{a.actor_type}{a.actor_reference ? ` · ${shortId(a.actor_reference)}` : ""}</Cell>
                  <Cell mono>{a.action_type}</Cell>
                  <Cell mono>{a.resource_type}</Cell>
                  <td>
                    <Badge group="outcome" value={a.outcome} />
                  </td>
                  <Cell muted>{a.reason ?? "—"}</Cell>
                  <Cell mono muted>
                    {a.tenant_id ? <Link to={`/admin/tenants/${a.tenant_id}`}>{shortId(a.tenant_id)}</Link> : "Platform"}
                  </Cell>
                </tr>
              ))}
              count={`${auditList.length} of ${auditItems.length} loaded${nextBefore ? "" : " (all matching records)"}`}
              empty={{ title: "No audit records match this filter", body: "Clear the filters." }}
            />
          )}
          {nextBefore ? <div className="submit-row"><button type="button" className="btn btn-secondary" onClick={() => void loadOlder()} disabled={loadingOlder}>{loadingOlder ? "Loading…" : "Load older records"}</button></div> : null}
        </>
      )}
      </div>
      <Footnote>Failures show the 50 most recent events. Audit records filter by full tenant id and action type on the server and page back through the whole history. Records are written by the platform and cannot be edited or deleted.</Footnote>
    </Page>
  );
}
