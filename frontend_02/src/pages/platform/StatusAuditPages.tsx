import { useState } from "react";
import { Link } from "react-router-dom";
import { platform } from "../../api";
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
      {status.error ? <ErrorBanner error={status.error} /> : null}
      {!s && status.loading ? (
        <Skeleton />
      ) : s ? (
        <>
          <Stats
            items={[
              { label: "Overall", value: s.status, tone: s.status === "healthy" ? "ok" : "warn" },
              { label: "API cluster", value: s.api_cluster },
              { label: "Database", value: s.database, tone: s.database === "connected" ? undefined : "danger" },
              { label: "Worker pool", value: s.worker_pool, note: s.worker_pool === "not_deployed" ? "training runs in the API in this release" : "" },
              { label: "Active tenants", value: tenants.data ? String(activeTenants) : "…", note: tenants.data ? `of ${tenants.data.items.length} accounts` : "" },
              { label: "Security events", value: recentFailures === undefined ? "…" : String(recentFailures), note: "last 24 hours" },
            ]}
          />
          <DefinitionList
            items={[
              { label: "Reported at", value: fmtDateTime(s.timestamp), mono: true },
              { label: "API cluster", badge: <Badge group="platform" value={s.api_cluster} /> },
              { label: "Database", badge: <Badge group="platform" value={s.database} /> },
              { label: "Worker pool", badge: <Badge group="platform" value={s.worker_pool} /> },
            ]}
          />
        </>
      ) : null}
      <Footnote>A gap in measurement is reported as a gap. It is never rendered as a zero.</Footnote>
    </Page>
  );
}

type Tab = "Failures" | "Audit records";

export function PlatformAuditPage() {
  const [tab, setTab] = useState<Tab>("Failures");
  const failures = useResource(() => platform.listFailures(), []);
  const audit = useResource(() => platform.listAudit(), []);
  const [severity, setSeverity] = useState("all severities");
  const [action, setAction] = useState("all action types");
  const [tenant, setTenant] = useState("");

  const failureList = (failures.data?.items ?? []).filter((f) => severity === "all severities" || f.severity === severity);
  const auditItems = audit.data?.items ?? [];
  const actionTypes = Array.from(new Set(auditItems.map((a) => a.action_type))).sort();
  const auditList = auditItems.filter((a) => (action === "all action types" || a.action_type === action) && (!tenant.trim() || a.tenant_id.startsWith(tenant.trim())));

  return (
    <Page crumbs={[{ label: "Platform", to: "/admin/status" }, { label: "Failures & Audit", to: "/admin/audit" }, { label: tab }]} kicker="Audit permission" title="Failures & Audit" subtitle={tab === "Failures" ? "Redacted security and failure events across the platform. Details are sanitized before they are stored." : "Immutable, append-only history. Sensitive details stay redacted."}>
      <Tabs tabs={["Failures", "Audit records"] as Tab[]} value={tab} onChange={setTab} />
      {tab === "Failures" ? (
        <>
          {failures.error ? <ErrorBanner error={failures.error} /> : null}
          <FilterBar filters={[{ id: "sev", label: "Severity", value: severity, onChange: setSeverity, options: ["all severities", ...Array.from(new Set((failures.data?.items ?? []).map((f) => f.severity))).sort()] }]} onClear={() => setSeverity("all severities")} />
          {failures.loading && !failures.data ? (
            <Skeleton />
          ) : (
            <DataTable
              minWidth={1000}
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
          {audit.error ? <ErrorBanner error={audit.error} /> : null}
          <FilterBar
            filters={[
              { id: "action", label: "Action type", value: action, onChange: setAction, options: ["all action types", ...actionTypes] },
              { id: "tenant", label: "Tenant id", value: tenant, onChange: setTenant, placeholder: "starts with…" },
            ]}
            onClear={() => {
              setAction("all action types");
              setTenant("");
            }}
          />
          {audit.loading && !audit.data ? (
            <Skeleton />
          ) : (
            <DataTable
              minWidth={1080}
              columns={["Occurred at", "Actor type", "Action type", "Resource type", "Outcome", "Tenant"]}
              rows={auditList.map((a) => (
                <tr key={a.id}>
                  <Cell mono>{fmtDateTime(a.occurred_at)}</Cell>
                  <Cell mono>{a.actor_type}</Cell>
                  <Cell mono>{a.action_type}</Cell>
                  <Cell mono>{a.resource_type}</Cell>
                  <td>
                    <Badge group="outcome" value={a.outcome} />
                  </td>
                  <Cell mono muted>
                    <Link to={`/admin/tenants/${a.tenant_id}`}>{shortId(a.tenant_id)}</Link>
                  </Cell>
                </tr>
              ))}
              count={`${auditList.length} of the ${auditItems.length} most recent`}
              empty={{ title: "No audit records match this filter", body: "Clear the filters." }}
            />
          )}
        </>
      )}
      <Footnote>The API returns the 50 most recent records of each kind. Records are written by the platform and cannot be edited or deleted from this console.</Footnote>
    </Page>
  );
}
