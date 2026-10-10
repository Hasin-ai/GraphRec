import { useState } from "react";
import { Link } from "react-router-dom";
import { platform } from "../../api";
import type { PlanRequestStatus, PlatformPlanRequest } from "../../api/types";
import { getPlatformSession, hasOperatorRole } from "../../auth/session";
import { useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Page } from "../../ui/Page";
import { ReasonField } from "../../ui/ReasonField";
import { ActionsCell, Cell, DataTable, ErrorBanner, Footnote, Skeleton, Tabs, Tag } from "../../ui/primitives";
import { useBelowUsageGuard } from "./TenantPages";

const VIEWS = ["Pending", "Approved", "Rejected", "Cancelled", "All"] as const;
type View = (typeof VIEWS)[number];
const STATUS_TONE: Record<PlanRequestStatus, "ok" | "warn" | "danger" | "neu"> = {
  pending: "warn", approved: "ok", rejected: "danger", cancelled: "neu",
};

/** The approval point: GraphRec takes no payments, so every plan change a tenant asks for lands here. */
export function PlatformPlanRequestsPage() {
  const [view, setView] = useQueryState("view", "Pending");
  const status = view === "All" ? undefined : (view.toLowerCase() as PlanRequestStatus);
  const requests = useResource(() => platform.listPlanRequests(status), [status]);
  const canDecide = hasOperatorRole(getPlatformSession(), "plan_management");
  const [deciding, setDeciding] = useState<{ request: PlatformPlanRequest; decision: "approve" | "reject" } | null>(null);
  const { flash } = useToast();
  const items = requests.data?.items ?? [];

  const rows = items.map((r) => (
    <tr key={r.id}>
      <Cell sub={r.tenant_name}><Link to={`/admin/tenants/${r.tenant_id}`} className="td-mono">{r.tenant_slug}</Link></Cell>
      <Cell sub={r.status === "pending" && r.active_plan_code && r.active_plan_code !== r.current_plan_code ? `Plan has since changed to ${r.active_plan_code}` : undefined}>
        {r.current_plan_name} → <b>{r.requested_plan_name}</b>
      </Cell>
      <Cell muted>{r.message || "—"}</Cell>
      <Cell mono sub={r.decided_at ? `Decided ${fmtDateTime(r.decided_at)}${r.decided_by_email ? ` by ${r.decided_by_email}` : ""}` : undefined}>{fmtDateTime(r.created_at)}</Cell>
      <Cell sub={r.decision_reason ?? undefined}><Tag tone={STATUS_TONE[r.status]} dot>{r.status}</Tag></Cell>
      {r.status === "pending" && canDecide ? (
        <ActionsCell actions={[
          { label: "Approve", onClick: () => setDeciding({ request: r, decision: "approve" }) },
          { label: "Reject", danger: true, onClick: () => setDeciding({ request: r, decision: "reject" }) },
        ]} />
      ) : <td />}
    </tr>
  ));

  return (
    <Page crumbs={[{ label: "Platform", to: "/admin/status" }, { label: "Plan requests" }]} kicker="Plan-management permission"
      title="Plan requests"
      subtitle="GraphRec takes no payments: tenants ask for Free demo, Basic or Pro here. Approving activates the plan immediately; rejecting keeps the current plan. The tenant sees your reason."
      actions={[{ label: "Refresh", disabled: requests.loading, onClick: () => void requests.reload() }]}>
      <Tabs tabs={[...VIEWS]} value={(VIEWS as readonly string[]).includes(view) ? (view as View) : "Pending"} onChange={setView} />
      {requests.error ? <ErrorBanner error={requests.error} onRetry={requests.reload} /> : null}
      {!requests.data ? (requests.loading ? <Skeleton /> : null) : (
        <DataTable minWidth={920} columns={["Tenant", "Plan change", "Message", "Requested", "Status", { label: "", align: "right" }]} rows={rows}
          count={`${items.length} ${view === "All" ? "requests" : view.toLowerCase()} · ${requests.data.pending_count} pending`}
          empty={{ title: view === "Pending" ? "No requests waiting" : "No requests", body: view === "Pending" ? "New plan requests from tenants appear here for approval." : "Requests in this state appear here." }} />
      )}
      {!canDecide ? <Footnote>You can see requests; approving or rejecting needs the plan-management role.</Footnote> : <Footnote>Every decision writes an audit record on the tenant, with your reason and the request correlation id.</Footnote>}
      {deciding ? <DecisionDialog {...deciding} onClose={() => setDeciding(null)} onDone={(message) => {
        setDeciding(null); flash(message); void requests.reload();
      }} /> : null}
    </Page>
  );
}

function DecisionDialog({ request, decision, onClose, onDone }: { request: PlatformPlanRequest; decision: "approve" | "reject"; onClose: () => void; onDone: (message: string) => void }) {
  const [reason, setReason] = useState("");
  const guard = useBelowUsageGuard();
  const approve = decision === "approve";
  return (
    <Dialog
      width={620}
      title={`${approve ? "Approve" : "Reject"} ${request.requested_plan_name} for ${request.tenant_slug}`}
      confirmLabel={approve ? `Approve and activate ${request.requested_plan_name}` : "Reject request"}
      confirmDisabled={reason.trim().length < 3}
      body={approve
        ? `${request.tenant_name} moves to ${request.requested_plan_name} as soon as you confirm. Usage is not reset and existing overrides stay.`
        : `${request.tenant_name} stays on its current plan. It can send a new request afterwards.`}
      facts={[
        { label: "Current plan", value: request.active_plan_code ?? request.current_plan_code },
        { label: "Requested plan", value: request.requested_plan_name },
        { label: "Requested", value: fmtDateTime(request.created_at) },
        ...(request.message ? [{ label: "Tenant's note", value: request.message }] : []),
      ]}
      onClose={() => { guard.reset(); onClose(); }}
      onConfirm={async () => {
        const result = await guard.attempt(ack => platform.decidePlanRequest(request.id, decision, reason, ack));
        if (!guard.isResult(result)) return result;
        onDone(approve
          ? `${request.tenant_slug} is now on ${request.requested_plan_name}.${result.warnings?.length ? " It is over a storage limit." : ""}`
          : `Request from ${request.tenant_slug} rejected.`);
      }}
    >
      <ReasonField id="plan-request-reason" value={reason} onChange={setReason} required />
      {guard.notice}
    </Dialog>
  );
}
