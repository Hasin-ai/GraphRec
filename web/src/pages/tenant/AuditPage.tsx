import { useEffect, useState } from "react";
import { tenantAudit } from "../../api";
import type { TenantAuditItem } from "../../api/types";
import { useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { fmtDateTime, humanize, shortId } from "../../lib/format";
import { Page } from "../../ui/Page";
import { Badge, Cell, DataTable, ErrorBanner, FilterBar, Footnote, Skeleton } from "../../ui/primitives";

function actor(item: TenantAuditItem): string {
  if (item.actor_type === "platform_operator") return "GraphRec operator";
  if (item.actor_type === "system") return "System";
  return `${humanize(item.actor_type)}${item.actor_reference ? ` ${shortId(item.actor_reference)}` : ""}`;
}

/** UC-31: this tenant's own audit trail. Platform operators are shown by role, never by identity. */
export function AuditPage() {
  const [action, setAction] = useQueryState("action", "all action types");
  const serverAction = action === "all action types" ? undefined : action;
  const audit = useResource(() => tenantAudit.list({ action: serverAction, limit: 100 }), [serverAction]);
  const [older, setOlder] = useState<{ items: TenantAuditItem[]; next: string | null } | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  useEffect(() => setOlder(null), [serverAction]);
  const items = [...(audit.data?.items ?? []), ...(older?.items ?? [])];
  const nextBefore = older ? older.next : audit.data?.next_before ?? null;
  const actionTypes = Array.from(new Set([...items.map(i => i.action_type), ...(serverAction ? [serverAction] : [])])).sort();
  async function loadOlder() {
    if (!nextBefore) return;
    setLoadingOlder(true);
    try {
      const page = await tenantAudit.list({ action: serverAction, before: nextBefore, limit: 100 });
      setOlder(previous => ({ items: [...(previous?.items ?? []), ...page.items], next: page.next_before }));
    } finally { setLoadingOlder(false); }
  }
  return <Page title="Audit trail" subtitle="Who changed what in this workspace, newest first. Records cannot be edited or deleted."
    crumbs={[{ label: "Overview", to: "/home" }, { label: "Audit trail" }]} actions={[{ label: "Refresh", onClick: () => void audit.reload(), disabled: audit.loading }]}>
    {audit.error ? <ErrorBanner error={audit.error} onRetry={audit.reload} /> : null}
    <FilterBar filters={[{ id: "action", label: "Action", value: action, onChange: setAction, options: ["all action types", ...actionTypes] }]} onClear={() => setAction("all action types")} />
    {!audit.data ? audit.loading ? <Skeleton /> : null : <DataTable minWidth={900}
      columns={["Occurred at", "Action", "Resource", "Outcome", "Actor", "Reason"]}
      rows={items.map(item => <tr key={item.id}>
        <Cell mono>{fmtDateTime(item.occurred_at)}</Cell>
        <Cell mono>{item.action_type}</Cell>
        <Cell sub={item.resource_reference ? shortId(item.resource_reference) : undefined}>{humanize(item.resource_type)}</Cell>
        <td><Badge group="outcome" value={item.outcome} /></td>
        <Cell>{actor(item)}</Cell>
        <Cell muted>{item.reason || "—"}</Cell>
      </tr>)}
      count={`${items.length} records`} empty={{ title: "No audit records", body: "Changes to members, keys, models and settings appear here." }} />}
    {nextBefore ? <div><button className="btn" onClick={() => void loadOlder()} disabled={loadingOlder}>{loadingOlder ? "Loading…" : "Load older records"}</button></div> : null}
    <Footnote>Actions by GraphRec operators are shown with the reason they gave, without naming the operator.</Footnote>
  </Page>;
}
