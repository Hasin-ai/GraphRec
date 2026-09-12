import { useParams } from "react-router-dom";
import { events } from "../../api";
import { isApiError } from "../../api/client";
import { useResource } from "../../hooks/useResource";
import { fmtDateTime, fmtNumber } from "../../lib/format";
import { Page } from "../../ui/Page";
import { Badge, DefinitionList, ErrorBanner, Footnote, Skeleton, StageRail, Stats } from "../../ui/primitives";
import { NotFoundPage } from "../errors/ErrorPages";

const STAGES = ["received", "validating", "applying", "completed"] as const;

/** Event-batch result. Product synchronization is synchronous and has no submission record. */
export function SubmissionPage() {
  const { submissionId = "" } = useParams();
  const batch = useResource(() => events.getBatch(submissionId), [submissionId]);
  const crumbs = [{ label: "Home", to: "/home" }, { label: "Submit Events", to: "/events/submit" }, { label: submissionId, mono: true }];

  if (batch.error && isApiError(batch.error) && (batch.error.status === 404 || batch.error.status === 422)) return <NotFoundPage />;
  if (!batch.data) {
    return (
      <Page crumbs={crumbs} kicker="event batch" title={`Submission ${submissionId}`}>
        {batch.error ? <ErrorBanner error={batch.error} /> : <Skeleton />}
      </Page>
    );
  }
  const b = batch.data;
  const received = b.accepted_count + b.duplicate_count + b.rejected_count;
  const done = b.status === "completed";
  return (
    <Page crumbs={crumbs} kicker="event batch" title={`Submission ${b.id}`} badge={<Badge group="batch" value={b.status} />} subtitle={done ? "Processing finished." : "Processing."} actions={[{ label: "Refresh", onClick: () => void batch.reload() }]}>
      <StageRail title="Progress" stages={STAGES} at={done ? 3 : 2} failed={b.status === "failed"} note={done ? "All items handled." : "Reload to update the counts."} />
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
          { label: "Kind", value: "event batch" },
          { label: "Submitted at", value: fmtDateTime(b.created_at), mono: true },
          { label: "Status", badge: <Badge group="batch" value={b.status} /> },
        ]}
      />
      <Footnote>Per-item rejection reasons are not retained by the API; rejected items are counted only. Raw payloads are never echoed back.</Footnote>
    </Page>
  );
}
