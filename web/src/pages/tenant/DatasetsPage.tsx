import { useRef, useState } from "react";
import { datasets, training } from "../../api";
import { describeError } from "../../api/client";
import type { DatasetUploadResponse } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtBytes, fmtDateTime, fmtNumber, shortId } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Field, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Banner, DataTable, IdChip, ErrorBanner, Footnote, Panel, Skeleton, Stats } from "../../ui/primitives";

export function DatasetsPage() {
  const { can } = useSession();
  const { flash } = useToast();
  const snapshots = useResource(() => datasets.listSnapshots(), []);
  const { can: canDo } = useSession();
  const runs = useResource(() => canDo("training:read") ? training.list() : Promise.resolve(null), [canDo("training:read")]);
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const [uploaded, setUploaded] = useState<DatasetUploadResponse | null>(null);
  const [creating, setCreating] = useState(false);
  const [cutoff, setCutoff] = useState("");
  const canUpload = can("catalog:write") && can("events:write");
  const canSnapshot = can("training:write");

  async function upload() {
    if (!file || uploading) return;
    setUploading(true);
    setUploadError(null);
    setUploaded(null);
    try {
      const result = await datasets.upload(file);
      setUploaded(result);
      setFile(null);
      if (input.current) input.current.value = "";
      flash(`Dataset accepted: ${fmtNumber(result.accepted_products)} products, ${fmtNumber(result.accepted_events)} events.`);
      void snapshots.reload();
    } catch (caught) {
      setUploadError(caught);
    } finally {
      setUploading(false);
    }
  }

  // Usage comes from the training runs: the API leaves snapshot.training_job_id empty (backend list).
  const usedBy = (id: string) => (runs.data?.items ?? []).filter(j => j.dataset_snapshot_id === id).length;
  const snaps = (snapshots.data?.items ?? []).slice().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const rows = snaps.map((s, i) => {
    const prev = snaps[i + 1];
    const n = usedBy(s.id) || (s.training_job_id ? 1 : 0);
    const delta = prev ? [s.event_count - prev.event_count ? `${s.event_count - prev.event_count > 0 ? "+" : ""}${fmtNumber(s.event_count - prev.event_count)} events` : null, s.product_count - prev.product_count ? `${s.product_count - prev.product_count > 0 ? "+" : ""}${fmtNumber(s.product_count - prev.product_count)} products` : null].filter(Boolean).join(", ") : "";
    return (
    <tr key={s.id}>
      <td>
        <div className="row" style={{ gap: 8 }}><IdChip value={s.id} label="Snapshot ID" />{i === 0 ? <span className="tag" style={{ background: "var(--info-bg)", color: "var(--info)" }}>Latest</span> : null}</div>
        <div className="sub">{n ? `Used by ${n} training ${n === 1 ? "run" : "runs"}` : "Not used yet"}{delta ? ` · ${delta} vs previous` : prev ? " · same counts as previous" : ""}</div>
      </td>
      <td data-hide-mobile>{fmtDateTime(s.cutoff_at)}</td>
      <td className="num">{fmtNumber(s.event_count)}</td>
      <td className="num">{fmtNumber(s.product_count)}</td>
      <td className="num" data-hide-mobile>{fmtNumber(s.user_count)}</td>
    </tr>
  ); });

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Datasets" }]}
      kicker="Training data"
      title="Datasets"
      subtitle="Import data and create immutable snapshots for model preparation."
      actions={canSnapshot ? [{ label: "Take snapshot", variant: "primary", onClick: () => setCreating(true) }] : []}
    >
      {canUpload ? (
        <details className="details-section"><summary>Import products and events from a file</summary><Panel title="Upload a dataset file" body="Choose a JSON or CSV file. The import updates products, submits events and creates a snapshot.">
          <details><summary>Supported file formats</summary><p className="footnote">JSON: an object with products and events arrays, or an array of mixed records. CSV: rows identified by event_id or external_id. Interaction logs with user_id,item_id,time are also supported; items become products and rows become purchase events.</p></details>
          <div className="file-drop">
            <input
              ref={input}
              disabled={uploading}
              type="file"
              accept=".json,.csv,application/json,text/csv"
              aria-label="Dataset file"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setUploadError(null);
              }}
            />
            <div className="row">
              <button type="button" className="btn btn-primary" disabled={!file || uploading} onClick={() => void upload()}>
                {uploading ? "Uploading…" : "Upload dataset"}
              </button>
              {file ? (
                <span className="small muted mono">
                  {file.name} · {fmtBytes(file.size)}
                </span>
              ) : null}
            </div>
          </div>
          {uploadError ? <ErrorBanner error={uploadError} title="The dataset was not accepted" /> : null}
          {uploaded ? (
            <Stats
              items={[
                { label: "Accepted products", value: fmtNumber(uploaded.accepted_products) },
                { label: "Accepted events", value: fmtNumber(uploaded.accepted_events) },
                { label: "Snapshot", value: shortId(uploaded.dataset_snapshot.id, 13), note: `${fmtNumber(uploaded.dataset_snapshot.event_count)} events in snapshot` },
              ]}
            />
          ) : null}
        </Panel></details>
      ) : (
        <Banner tone="info" title="Upload not offered">
          Uploading requires both catalog:write and events:write. Snapshot creation separately requires training:write.
        </Banner>
      )}
      {snapshots.error ? <ErrorBanner error={snapshots.error} onRetry={snapshots.reload} /> : null}
      {!snapshots.data ? (snapshots.loading ? <Skeleton /> : null) : (
        <DataTable
          title="Dataset snapshots"
          minWidth={820}
          columns={["Snapshot", "Data up to", { label: "Events", align: "right" }, { label: "Products", align: "right" }, { label: "Users", align: "right" }]}
          rows={rows}
          count={`${rows.length} snapshots`}
          empty={{ title: "No snapshots yet", body: "Upload a dataset or take a snapshot of the current catalog and events.", action: canSnapshot ? { label: "Take snapshot", onClick: () => setCreating(true) } : undefined }}
        />
      )}
      <Footnote>Snapshots are immutable. Training requests can reference one by identifier; without one, the backend uses the live catalog.</Footnote>
      {creating ? (
        <Dialog
          title="Take a dataset snapshot"
          width={600}
          confirmLabel="Create snapshot"
          body="Freezes the events and products up to the cutoff into an immutable snapshot a training job can build from."
          onConfirm={async () => {
            if (cutoff.trim() && Number.isNaN(new Date(cutoff).getTime())) return "Use an ISO-8601 timestamp for the cutoff, or leave it empty.";
            try {
              await datasets.createSnapshot({ cutoff_at: cutoff.trim() ? new Date(cutoff).toISOString() : null });
            } catch (caught) {
              return describeError(caught);
            }
            setCreating(false);
            setCutoff("");
            flash("Snapshot created.");
            void snapshots.reload();
          }}
          onClose={() => setCreating(false)}
        >
          <Field id="d-cutoff" label="Cutoff (optional)" hint="Defaults to now.">
            <TextInput id="d-cutoff" value={cutoff} onChange={setCutoff} mono placeholder="2026-08-14T00:00:00Z" />
          </Field>
        </Dialog>
      ) : null}
    </Page>
  );
}
