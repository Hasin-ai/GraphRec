import { useState } from "react";
import { datasets } from "../../api";
import { isApiError, describeError } from "../../api/client";
import type { DatasetUploadResponse } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtBytes, fmtDateTime, fmtNumber, shortId } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Field, TextArea, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Banner, Cell, CopyButton, DataTable, ErrorBanner, Footnote, Panel, Skeleton, Stats } from "../../ui/primitives";

const MAX_UPLOAD = 10 * 1024 * 1024;

export function DatasetsPage() {
  const { can } = useSession();
  const { flash } = useToast();
  const snapshots = useResource(() => datasets.listSnapshots(), []);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const [uploaded, setUploaded] = useState<DatasetUploadResponse | null>(null);
  const [creating, setCreating] = useState(false);
  const [cutoff, setCutoff] = useState("");
  const [description, setDescription] = useState("");
  const canUpload = can("catalog:write") && can("events:write");
  const canSnapshot = can("training:write");

  async function upload() {
    if (!file) return;
    if (file.size > MAX_UPLOAD) {
      setUploadError(new Error("too large"));
      return;
    }
    setUploading(true);
    setUploadError(null);
    setUploaded(null);
    try {
      const result = await datasets.upload(file);
      setUploaded(result);
      setFile(null);
      flash(`Dataset accepted: ${fmtNumber(result.accepted_products)} products, ${fmtNumber(result.accepted_events)} events.`);
      void snapshots.reload();
    } catch (caught) {
      setUploadError(caught);
    } finally {
      setUploading(false);
    }
  }

  const rows = (snapshots.data?.items ?? []).map((s) => (
    <tr key={s.id}>
      <Cell mono sub={s.training_job_id ? `job ${shortId(s.training_job_id)}` : undefined}>
        {shortId(s.id, 13)} <CopyButton value={s.id} label="Copy id" />
      </Cell>
      <Cell mono>{fmtDateTime(s.cutoff_at)}</Cell>
      <Cell mono align="right">
        {fmtNumber(s.event_count)}
      </Cell>
      <Cell mono align="right">
        {fmtNumber(s.product_count)}
      </Cell>
      <Cell mono align="right">
        {fmtNumber(s.user_count)}
      </Cell>
      <Cell mono muted>
        {s.checksum.slice(0, 12)}…
      </Cell>
      <Cell mono>{fmtDateTime(s.created_at)}</Cell>
    </tr>
  ));

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Datasets" }]}
      kicker="Training data"
      title="Datasets"
      subtitle="Upload a JSON or CSV file of products and events in one step, or take a snapshot of what the tenant already holds. A training job builds from a snapshot."
      actions={canSnapshot ? [{ label: "Take snapshot", variant: "primary", onClick: () => setCreating(true) }] : []}
    >
      {canUpload ? (
        <Panel title="Upload a dataset file" body="A JSON object with products and events arrays, a JSON array of mixed records, or a CSV whose rows carry event_id (event) or external_id (product). Up to 10 MiB. The upload upserts the catalog, submits the events and takes a snapshot.">
          <div className="file-drop">
            <input
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
          {uploadError ? (
            isApiError(uploadError) ? (
              <ErrorBanner error={uploadError} title="The dataset was not accepted" />
            ) : (
              <Banner tone="warn" title="File too large">
                The upload limit is {fmtBytes(MAX_UPLOAD)}. Split the file and upload it in parts.
              </Banner>
            )
          ) : null}
          {uploaded ? (
            <Stats
              items={[
                { label: "Accepted products", value: fmtNumber(uploaded.accepted_products) },
                { label: "Accepted events", value: fmtNumber(uploaded.accepted_events) },
                { label: "Snapshot", value: shortId(uploaded.dataset_snapshot.id, 13), note: `${fmtNumber(uploaded.dataset_snapshot.event_count)} events in snapshot` },
              ]}
            />
          ) : null}
        </Panel>
      ) : (
        <Banner tone="info" title="Upload not offered">
          Uploading requires both catalog:write and events:write. Snapshots below are read-only for this credential.
        </Banner>
      )}
      {snapshots.error ? <ErrorBanner error={snapshots.error} /> : null}
      {snapshots.loading && !snapshots.data ? (
        <Skeleton />
      ) : (
        <DataTable
          title="Dataset snapshots"
          minWidth={1000}
          columns={["Snapshot", "Cutoff", { label: "Events", align: "right" }, { label: "Products", align: "right" }, { label: "Users", align: "right" }, "Checksum", "Created"]}
          rows={rows}
          count={`${rows.length} snapshots`}
          empty={{ title: "No snapshots yet", body: "Upload a dataset or take a snapshot of the current catalog and events.", action: canSnapshot ? { label: "Take snapshot", onClick: () => setCreating(true) } : undefined }}
        />
      )}
      <Footnote>Snapshots are immutable. Training jobs reference one by identifier; without one the job trains from the live catalog.</Footnote>
      {creating ? (
        <Dialog
          title="Take a dataset snapshot"
          width={600}
          confirmLabel="Create snapshot"
          body="Freezes the events and products up to the cutoff into an immutable snapshot a training job can build from."
          onConfirm={async () => {
            if (cutoff.trim() && Number.isNaN(new Date(cutoff).getTime())) return "Use an ISO-8601 timestamp for the cutoff, or leave it empty.";
            try {
              await datasets.createSnapshot({ cutoff_at: cutoff.trim() ? new Date(cutoff).toISOString() : null, description: description.trim() || null });
            } catch (caught) {
              return describeError(caught);
            }
            setCreating(false);
            setCutoff("");
            setDescription("");
            flash("Snapshot created.");
            void snapshots.reload();
          }}
          onClose={() => setCreating(false)}
        >
          <Field id="d-cutoff" label="Cutoff (optional)" hint="Defaults to now.">
            <TextInput id="d-cutoff" value={cutoff} onChange={setCutoff} mono placeholder="2026-08-14T00:00:00Z" />
          </Field>
          <Field id="d-desc" label="Description (optional)">
            <TextArea id="d-desc" rows={2} value={description} onChange={setDescription} />
          </Field>
        </Dialog>
      ) : null}
    </Page>
  );
}
