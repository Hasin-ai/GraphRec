import { useParams } from "react-router-dom";
import { events } from "../../api";
import { isApiError } from "../../api/client";
import { useResource } from "../../hooks/useResource";
import { fmtDateTime, fmtNumber } from "../../lib/format";
import { Page } from "../../ui/Page";
import { Badge, Cell, DefinitionList, ErrorBanner, Panel, PanelTable, Skeleton, Stats } from "../../ui/primitives";
import { NotFoundPage } from "../errors/ErrorPages";

/** Durable event-batch result and item outcomes. */
export function SubmissionPage() {
  const { submissionId = "" } = useParams();
  const batch = useResource(() => events.getBatch(submissionId), [submissionId]);
  const crumbs = [{ label: "Home", to: "/home" }, { label: "Submit Events", to: "/events/submit" }, { label: submissionId, mono: true }];

  if (batch.error && isApiError(batch.error) && (batch.error.status === 404 || batch.error.status === 422)) return <NotFoundPage />;
  if (!batch.data) {
    return (
      <Page crumbs={crumbs} kicker="event batch" title={`Submission ${submissionId}`}>
        {batch.error ? <ErrorBanner error={batch.error} onRetry={batch.reload} /> : <Skeleton />}
      </Page>
    );
  }
  const b = batch.data;
  const received = b.accepted_count + b.duplicate_count + b.rejected_count;
  const done = b.status === "completed";
  return (
    <Page crumbs={crumbs} kicker="event batch" title={`Event batch · ${fmtDateTime(b.created_at)}`} badge={<Badge group="batch" value={b.status} />} subtitle={done ? "The batch was applied in the request that submitted it; these are its final counts." : "Reload to update the counts."} actions={[{ label: "Refresh", onClick: () => void batch.reload() }]}>
      {batch.error ? <ErrorBanner error={batch.error} onRetry={batch.reload} /> : null}
      <Stats
        items={[
          { label: "Received", value: fmtNumber(received) },
          { label: "Accepted", value: fmtNumber(b.accepted_count) },
          { label: "Duplicates", value: fmtNumber(b.duplicate_count), note: "already received; not counted twice" },
          { label: "Rejected", value: fmtNumber(b.rejected_count), tone: b.rejected_count ? "danger" : undefined },
        ]}
      />
      <DefinitionList
        items={[
          { label: "Submission id", value: b.id, mono: true, copy: b.id },
          ...(b.request_id ? [{ label: "Request id", value: b.request_id, mono: true }] : []),
          { label: "Kind", value: "event batch" },
          { label: "Submitted at", value: fmtDateTime(b.created_at), mono: true },
          { label: "Status", badge: <Badge group="batch" value={b.status} /> },
        ]}
      />
      <Panel title="Item outcomes" note={`${b.outcomes?.length ?? 0} retained`} body="Each event identifier has a safe processing result. Raw event context is not returned.">
        {b.outcomes?.length ? <PanelTable columns={["Event id", "Outcome", "Reason"]} rows={b.outcomes.map((o, i) => <tr key={`${o.event_id}-${i}`}>
          <Cell mono>{o.event_id}</Cell><Cell>{o.status}</Cell><Cell muted>{o.reason ?? "—"}</Cell>
        </tr>)} /> : <p className="p-body">This older submission has no retained item outcomes.</p>}
      </Panel>
    </Page>
  );
}
