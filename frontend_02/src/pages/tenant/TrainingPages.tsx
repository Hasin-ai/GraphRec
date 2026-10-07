import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { billing, datasets, models, training } from "../../api";
import { isApiError } from "../../api/client";
import type { TrainingJobResource } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useMeta } from "../../hooks/useMeta";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, fmtNumber, shortId, flattenMetrics } from "../../lib/format";
import { humanizeKey, jobLabel, modelTypeLabel } from "../../lib/labels";
import { IdChip } from "../../ui/primitives";

function durationLabel(start: string, end: string): string {
  const s = Math.max(0, Math.round((Date.parse(end) - Date.parse(start)) / 1000));
  return s < 60 ? `Completed in ${s} s` : s < 3600 ? `Completed in ${Math.round(s / 60)} min` : `Completed in ${(s / 3600).toFixed(1)} h`;
}
const humanizeValue = (key: string, value: string) => key === "mode" ? humanizeKey(value) : value;
import { quotaState } from "../../lib/quota";
import { useQueryState } from "../../hooks/useQueryState";
import { JOB_STATES } from "../../lib/status";
import { Dialog } from "../../ui/Dialog";
import { Field, Select, TextArea, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { QualitySummary } from "../../ui/QualitySummary";
import { ActionsCell, Badge, Cell, DataTable, DefinitionList, ErrorBanner, FilterBar, Panel, Skeleton, Banner } from "../../ui/primitives";
import { NotFoundPage } from "../errors/ErrorPages";
import { RetrainingPolicyPanel } from "./RetrainingPolicyPanel";

/** The worker records detailed stages while status remains queued or running. */
const ACTIVE_STATES = ["queued", "running"];

interface Eligibility {
  ok: boolean;
  reason: string;
}

export function eligibility(jobs: TrainingJobResource[] | undefined, trainingRemaining: number | null | undefined, canWrite: boolean): Eligibility {
  if (!canWrite) return { ok: false, reason: "Requesting training requires training:write." };
  const running = jobs?.find((j) => ACTIVE_STATES.includes(j.status));
  if (running) return { ok: false, reason: 'Another training run is still in progress. Wait for it to finish before starting a new one.' };
  if (trainingRemaining === 0) return { ok: false, reason: "The training quota for this period is exhausted." };
  return { ok: true, reason: "" };
}

function StartTrainingDialog({ el, onClose, onStarted }: { el: Eligibility; onClose: () => void; onStarted: (job: TrainingJobResource) => void }) {
  const snapshots = useResource(() => datasets.listSnapshots(), []);
  const [snapshot, setSnapshot] = useState("");
  const [config, setConfig] = useState("");
  const [mode, setMode] = useState("train");
  const productMeta = useMeta();
  const [artifact, setArtifact] = useState("");
  const [requestId] = useState(() => crypto.randomUUID());
  return (
    <Dialog
      title="Start training"
      width={640}
      confirmLabel="Request training"
      confirmDisabled={!el.ok || snapshots.loading || !!snapshots.error}
      body="Create a model version. Activation is a separate step."
      consequence={mode === 'train' ? 'Trains a DGSR model from an immutable tenant snapshot. Local CPU training supports up to 20,000 events, 10,000 products and 10 epochs. Activation remains a separate step.' : mode === 'checkpoint' ? 'Imports a DGSR checkpoint prepared on the API host. The backend verifies its compatibility with this tenant.' : 'Development only: creates synthetic embeddings, not a trained model. This consumes training quota.'}
      onConfirm={async () => {
        if (!el.ok) return el.reason;
        let configuration: Record<string, unknown> | undefined;
        if (config.trim()) {
          try {
            const parsed = JSON.parse(config) as unknown;
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return "Configuration must be a JSON object.";
            configuration = parsed as Record<string, unknown>;
          } catch {
            return "Configuration is not valid JSON.";
          }
        }
        if (mode === "checkpoint" && !artifact.trim()) return "Enter the checkpoint directory name configured by your operator.";
        configuration = { ...configuration };
        configuration.mode = mode;
        if (mode === "checkpoint") configuration.pretrained_artifact = artifact.trim();
        else delete configuration.pretrained_artifact;
        onStarted(await training.create({ request_id: requestId, dataset_snapshot_id: snapshot || null, ...(configuration ? { configuration } : {}) }));
      }}
      onClose={onClose}
    >
      <Field id="d-mode" label="Model source"><Select id="d-mode" value={mode} onChange={setMode} options={[{ value: "train", label: "Train from tenant data" }, { value: "checkpoint", label: "Trained DGSR checkpoint" }, ...(productMeta?.features.development_placeholders ? [{ value: "placeholder", label: "Placeholder — development only" }] : [])]} /></Field>
      {mode === "checkpoint" ? <Field id="d-artifact" label="Checkpoint directory" hint="Directory name under the API's configured model artifact root."><TextInput id="d-artifact" value={artifact} onChange={setArtifact} /></Field> : null}
      {snapshots.error ? <ErrorBanner error={snapshots.error} title="Snapshots unavailable" onRetry={snapshots.reload} /> : null}
      <Field id="d-snapshot" label="Dataset snapshot" hint="Training requires at least four product interactions for a shopper, including held-out validation and test targets.">
        <Select
          id="d-snapshot"
          value={snapshot}
          onChange={setSnapshot}
          options={[{ value: "", label: "Capture current tenant data" }, ...(snapshots.data?.items ?? []).map((s) => ({ value: s.id, label: `${shortId(s.id, 13)} · ${fmtDateTime(s.cutoff_at)} · ${fmtNumber(s.event_count)} events` }))]}
        />
      </Field>
      <Field id="d-config" label="Configuration (optional JSON)" hint="Optional backend configuration. Checkpoint selection above takes precedence.">
        <TextArea id="d-config" rows={3} value={config} onChange={setConfig} mono placeholder='{ "epochs": 3 }' />
      </Field>
    </Dialog>
  );
}

export function TrainingPage() {
  const { can } = useSession();
  const { flash } = useToast();
  const navigate = useNavigate();
  const jobs = useResource(() => training.list(), []);
  const usage = useResource(() => (can("usage:read") ? billing.usage() : Promise.resolve(null)), [can("usage:read")]);
  const [state, setState] = useQueryState("status", "all states");
  const [starting, setStarting] = useState(false);

  const trainingDim = usage.data?.dimensions.find((d) => d.type === "training_jobs");
  const checking = jobs.loading || (can("usage:read") && usage.loading);
  const unavailable = !!jobs.error || (can("usage:read") && (!!usage.error || !trainingDim));
  const el = !can("training:write") ? eligibility(undefined, undefined, false)
    : checking ? { ok: false, reason: "Checking training and quota…" }
    : unavailable ? { ok: false, reason: "Training availability could not be verified. Refresh to try again." }
    : eligibility(jobs.data?.items, trainingDim ? quotaState(trainingDim.used, trainingDim.limit).remaining : undefined, true);
  useEffect(() => {
    if (!jobs.data?.items.some(job => ACTIVE_STATES.includes(job.status))) return;
    const timer = window.setInterval(() => { if (!document.hidden) { void jobs.reload(); void usage.reload(); } }, 5000);
    return () => window.clearInterval(timer);
  }, [jobs.data, jobs.reload, usage.reload]);
  const list = (jobs.data?.items ?? []).filter((j) => state === "all states" || j.status === state);

  const rows = list.map((j) => (
    <tr key={j.id}>
      <td>
        <Link to={`/training/${j.id}`}>{jobLabel(j, jobs.data?.items ?? [])}</Link>
        <div className="sub mono">{shortId(j.id)}</div>
      </td>
      <td>
        <Badge group="job" value={j.status} />
      </td>
      <Cell>{modelTypeLabel(j.model_type)}</Cell>
      <Cell>{fmtDateTime(j.created_at)}</Cell>
      <Cell sub={j.status === "failed" && j.failure_reason ? j.failure_reason : undefined}>{j.completed_at ? fmtDateTime(j.completed_at) : ACTIVE_STATES.includes(j.status) ? "In progress" : "—"}</Cell>
      <Cell muted>
        {j.dataset_snapshot_id ? <span className="mono">{shortId(j.dataset_snapshot_id)}</span> : "Live data"}
      </Cell>
      <ActionsCell actions={[{ label: "Open", onClick: () => navigate(`/training/${j.id}`) }]} />
    </tr>
  ));

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Training" }]}
      kicker="Model production"
      title="Training"
      subtitle="Review jobs and prepare a model for activation."
      actions={[{ label: "Start training", variant: "primary", disabled: !el.ok, reason: el.reason, onClick: () => setStarting(true) }, { label: "Refresh", onClick: () => { void jobs.reload(); void usage.reload(); } }]}
    >
      {jobs.error ? <ErrorBanner error={jobs.error} onRetry={jobs.reload} /> : null}
      {usage.error ? <ErrorBanner error={usage.error} title="Usage unavailable" onRetry={usage.reload} /> : null}
      <p className="footnote">Start a run to train a DGSR model on your tenant data, or to import a prepared checkpoint. New versions are registered as eligible; activating one is a separate step.</p>
      {trainingDim ? <p className="footnote">Training jobs this period: {fmtNumber(trainingDim.used)} / {trainingDim.limit === null ? 'no limit' : fmtNumber(trainingDim.limit)}. Resets {fmtDateTime(usage.data?.reset_at)}.</p> : !can('usage:read') ? <p className="footnote">Your session cannot read quotas. The API checks limits when you submit.</p> : null}
      <FilterBar filters={[{ id: "state", label: "State", value: state, onChange: setState, options: ["all states", ...JOB_STATES] }]} onClear={() => setState("all states")} />
      {!jobs.data ? (jobs.loading ? <Skeleton /> : null) : (
        <DataTable
          minWidth={980}
          columns={["Job", "State", "Model type", "Requested at", "Completed at", "Snapshot", { label: "", align: "right" }]}
          rows={rows}
          count={`${list.length} of ${jobs.data?.items.length ?? 0}`}
          empty={{ title: state === "all states" ? "No training jobs yet" : "No jobs match this filter", body: state === "all states" ? "Request training to produce your first model version." : "Choose another state or clear the filter.", action: el.ok ? { label: "Start training", onClick: () => setStarting(true) } : undefined }}
        />
      )}
      <RetrainingPolicyPanel />
      {starting ? (
        <StartTrainingDialog
          el={el}
          onClose={() => setStarting(false)}
          onStarted={(job) => {
            setStarting(false);
            flash(`Training run ${job.status}.`);
            navigate(`/training/${job.id}`);
          }}
        />
      ) : null}
    </Page>
  );
}

export function TrainingJobPage() {
  const [cancelling, setCancelling] = useState(false);
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const jobResource = useResource(() => training.get(jobId), [jobId]);
  const job = jobResource.data;
  const { can } = useSession();
  const version = useResource(async () => (job?.model_version_id && can("models:read") ? models.get(job.model_version_id) : null), [job?.model_version_id, can("models:read")]);
  useEffect(() => {
    if (!job || !ACTIVE_STATES.includes(job.status)) return;
    const timer = window.setInterval(() => { if (!document.hidden) void jobResource.reload(); }, 5000);
    return () => window.clearInterval(timer);
  }, [job?.status, jobResource.reload]);
  const crumbs = [{ label: "Home", to: "/home" }, { label: "Training", to: "/training" }, { label: shortId(jobId, 13), mono: true }];

  if (jobResource.error && isApiError(jobResource.error) && jobResource.error.status === 404) return <NotFoundPage />;
  if (!job) {
    return (
      <Page crumbs={crumbs} kicker="Training job" title={shortId(jobId, 13)}>
        {jobResource.error ? <ErrorBanner error={jobResource.error} onRetry={jobResource.reload} /> : <Skeleton />}
      </Page>
    );
  }
  const active = ACTIVE_STATES.includes(job.status);
  const failed = job.status === "failed";
  const done = job.status === "succeeded";
  const v = version.data;
  const metricEntries = v ? flattenMetrics(v.metrics) : [];

  return (
    <Page
      crumbs={crumbs}
      kicker="Training run"
      title={`${modelTypeLabel(job.model_type)} training run`}
      badge={<Badge group="job" value={job.status} />}
      subtitle={active ? "The job is running. Status updates automatically while this page is visible." : done ? "The job completed and registered a model version. Activation is a separate, deliberate action." : failed ? "The job stopped before producing a version." : undefined}
      actions={[
        ...(active && can('training:write') ? [{ label: job.cancel_requested ? 'Cancellation requested' : 'Cancel job', disabled: job.cancel_requested, onClick: () => setCancelling(true) }] : []),
        { label: "Refresh", onClick: () => void jobResource.reload() },
      ]}
    >
      {jobResource.error ? <ErrorBanner error={jobResource.error} onRetry={jobResource.reload} /> : null}
      {version.error ? <ErrorBanner error={version.error} title="Model details unavailable" onRetry={version.reload} /> : null}
      {!job.configuration?.pretrained_artifact && job.configuration?.mode !== 'train' ? <Banner tone="warn" title="Development placeholder">This job uses synthetic embeddings. A succeeded status confirms the backend operation, not a trained recommendation model.</Banner> : null}
      <DefinitionList
        items={[
          active ? { label: 'Progress', value: `${job.progress ?? 0}% · ${String(job.stage ?? job.status).replace(/_/g, ' ')}` } : { label: 'Duration', value: job.completed_at ? durationLabel(job.created_at, job.completed_at) : '—' },
          { label: 'Source', value: job.configuration?.mode === 'pretrained_import' ? <>Imported checkpoint {typeof job.configuration?.pretrained_artifact === 'string' ? <IdChip value={job.configuration.pretrained_artifact as string} length={40} label="Checkpoint" /> : null}</> : 'Trained on tenant data' },
          { label: "Model type", value: modelTypeLabel(job.model_type) },
          { label: "Requested", value: fmtDateTime(job.created_at) },
          { label: "Completed", value: job.completed_at ? fmtDateTime(job.completed_at) : active ? "In progress" : "—" },
          { label: "Dataset snapshot", value: job.dataset_snapshot_id ?? "Live data", mono: !!job.dataset_snapshot_id, copy: job.dataset_snapshot_id ?? undefined },
          { label: "Produced version", value: v ? <><Link to={`/models/${v.id}`}>{v.version_tag}</Link> <Badge group="model" value={v.status} /></> : job.model_version_id ? shortId(job.model_version_id) : "None" },
          { label: "Run ID", value: job.id, mono: true, copy: job.id },
        ]}
      />
      <div className="panels">
        {done && v ? (
          <Panel title="Quality measures" badge={<Badge group="model" value={v.status} />} note={undefined} body={metricEntries.length ? 'Offline ranking scores for the version this run produced. Higher is better.' : "No offline metrics were recorded for this version. Train a DGSR model or import a checkpoint to record validation quality."} actions={[{ label: "Open model version", onClick: () => navigate(`/models/${v.id}`) }]}>
            {metricEntries.length ? <QualitySummary metrics={v.metrics} /> : null}
          </Panel>
        ) : null}
        {failed ? <Panel title="Failure reason" badge={<Badge group="job" value="failed" />} body={job.failure_reason ?? "No reason was recorded."} /> : null}
        <Panel title="Configuration" body="Settings this run used.">
          <dl className="kv-grid">{Object.entries(job.configuration ?? {}).map(([k, val]) => <div key={k}><dt>{humanizeKey(k)}</dt><dd className="small">{typeof val === 'string' ? humanizeValue(k, val) : JSON.stringify(val)}</dd></div>)}</dl>
          <details className="details-section"><summary>View as JSON</summary><pre className="secret-value" style={{ fontSize: 12.5 }}>{JSON.stringify(job.configuration ?? {}, null, 2)}</pre></details>
          {job.qdrant_collection ? <p className="p-body">Embedding index: <span className="mono">{job.qdrant_collection}</span></p> : null}
        </Panel>
      </div>
      {cancelling ? <Dialog title="Cancel training job" body="The worker stops at its next processing boundary. No model version is activated." confirmLabel="Cancel job" onClose={() => setCancelling(false)} onConfirm={async () => { await training.cancel(job.id); setCancelling(false); await jobResource.reload(); }} /> : null}
    </Page>
  );
}
