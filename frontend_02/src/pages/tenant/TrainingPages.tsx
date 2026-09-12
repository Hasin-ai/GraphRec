import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { billing, datasets, models, training } from "../../api";
import type { TrainingJobResource } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, fmtNumber, shortId } from "../../lib/format";
import { JOB_STAGES, jobStageIndex } from "../../lib/status";
import { Dialog } from "../../ui/Dialog";
import { Field, Select, TextArea } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { ActionsCell, Badge, Cell, DataTable, DefinitionList, ErrorBanner, FilterBar, Footnote, Panel, Skeleton, StageRail, Stats } from "../../ui/primitives";
import { NotFoundPage } from "../errors/ErrorPages";

const MODEL_TYPES = ["simplified_dgsr"];
const ACTIVE_STATES = ["queued", "preparing_data", "training"];

interface Eligibility {
  ok: boolean;
  reason: string;
}

function eligibility(jobs: TrainingJobResource[] | undefined, trainingRemaining: number | null | undefined, canWrite: boolean): Eligibility {
  if (!canWrite) return { ok: false, reason: "Requesting training requires training:write." };
  const running = jobs?.find((j) => ACTIVE_STATES.includes(j.status));
  if (running) return { ok: false, reason: `Job ${shortId(running.id)} is already running. Training concurrency is 1.` };
  if (trainingRemaining === 0) return { ok: false, reason: "The training quota for this period is exhausted." };
  return { ok: true, reason: "" };
}

function StartTrainingDialog({ el, onClose, onStarted }: { el: Eligibility; onClose: () => void; onStarted: (job: TrainingJobResource) => void }) {
  const snapshots = useResource(() => datasets.listSnapshots(), []);
  const [type, setType] = useState(MODEL_TYPES[0]);
  const [snapshot, setSnapshot] = useState("");
  const [config, setConfig] = useState("");
  return (
    <Dialog
      title="Start training"
      width={640}
      confirmLabel="Request training"
      body="A training job builds from a dataset snapshot, trains the model, registers an eligible version and indexes its embeddings. It does not activate anything."
      consequence={el.ok ? "In this release the job runs synchronously and returns as succeeded; model metrics are recorded by the training worker in a later slice." : `This request will be rejected: ${el.reason}`}
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
        onStarted(await training.create({ model_type: type, dataset_snapshot_id: snapshot || null, ...(configuration ? { configuration } : {}) }));
      }}
      onClose={onClose}
    >
      <Field id="d-type" label="Model type">
        <Select id="d-type" value={type} onChange={setType} options={MODEL_TYPES} />
      </Field>
      <Field id="d-snapshot" label="Dataset snapshot" hint={snapshots.data && !snapshots.data.items.length ? "No snapshot yet; the job trains from the live catalog." : undefined}>
        <Select
          id="d-snapshot"
          value={snapshot}
          onChange={setSnapshot}
          options={[{ value: "", label: "Latest data (no snapshot)" }, ...(snapshots.data?.items ?? []).map((s) => ({ value: s.id, label: `${shortId(s.id, 13)} · ${fmtDateTime(s.cutoff_at)} · ${fmtNumber(s.event_count)} events` }))]}
        />
      </Field>
      <Field id="d-config" label="Configuration (optional JSON)" hint='Defaults to { "batch_size": 256, "learning_rate": 0.001 }.'>
        <TextArea id="d-config" rows={3} value={config} onChange={setConfig} mono placeholder='{ "epochs": 20 }' />
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
  const [state, setState] = useState("all states");
  const [starting, setStarting] = useState(false);

  const trainingDim = usage.data?.dimensions.find((d) => d.type === "training_jobs");
  const eventsDim = usage.data?.dimensions.find((d) => d.type === "accepted_events");
  const el = eligibility(jobs.data?.items, trainingDim?.remaining, can("training:write"));
  const list = (jobs.data?.items ?? []).filter((j) => state === "all states" || j.status === state);

  const rows = list.map((j) => (
    <tr key={j.id}>
      <td>
        <Link to={`/training/${j.id}`} className="td-mono">
          {shortId(j.id, 13)}
        </Link>
      </td>
      <td>
        <Badge group="job" value={j.status} />
      </td>
      <Cell mono>{j.model_type}</Cell>
      <Cell mono>{fmtDateTime(j.created_at)}</Cell>
      <Cell mono>{fmtDateTime(j.completed_at)}</Cell>
      <Cell mono muted>
        {j.dataset_snapshot_id ? shortId(j.dataset_snapshot_id) : "live data"}
      </Cell>
      <ActionsCell actions={[{ label: "Open", onClick: () => navigate(`/training/${j.id}`) }]} />
    </tr>
  ));

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Training" }]}
      kicker="Model production"
      title="Training"
      subtitle="Offline batch training with a concurrency of one job. A request is accepted only when data, quota and scope all allow it."
      actions={[{ label: "Start training", variant: "primary", disabled: !el.ok, reason: el.reason, onClick: () => setStarting(true) }]}
    >
      {jobs.error ? <ErrorBanner error={jobs.error} /> : null}
      <Stats
        items={[
          { label: "Concurrency", value: "1", note: "platform-wide" },
          { label: "Eligibility", value: el.ok ? "eligible" : "blocked", note: el.ok ? "a request would be accepted" : el.reason, tone: el.ok ? "ok" : "warn" },
          { label: "Interaction data", value: eventsDim ? fmtNumber(eventsDim.used) : usage.loading ? "…" : "n/a", note: eventsDim ? "accepted events this period" : "usage:read not held" },
          { label: "Training quota", value: trainingDim ? `${fmtNumber(trainingDim.used)} / ${trainingDim.limit === null ? "∞" : fmtNumber(trainingDim.limit)}` : usage.loading ? "…" : "n/a", note: usage.data ? `resets ${fmtDateTime(usage.data.reset_at)}` : "" },
          { label: "Jobs", value: String(jobs.data?.items.length ?? 0), note: `${jobs.data?.items.filter((j) => j.status === "succeeded").length ?? 0} succeeded` },
        ]}
      />
      <FilterBar filters={[{ id: "state", label: "State", value: state, onChange: setState, options: ["all states", ...JOB_STAGES, "failed"] }]} onClear={() => setState("all states")} />
      {jobs.loading && !jobs.data ? (
        <Skeleton />
      ) : (
        <DataTable
          minWidth={980}
          columns={["Job", "State", "Model type", "Requested at", "Completed at", "Snapshot", { label: "", align: "right" }]}
          rows={rows}
          count={`${list.length} of ${jobs.data?.items.length ?? 0}`}
          empty={{ title: "No training jobs yet", body: "Request training to produce your first model version.", action: el.ok ? { label: "Start training", onClick: () => setStarting(true) } : undefined }}
        />
      )}
      {starting ? (
        <StartTrainingDialog
          el={el}
          onClose={() => setStarting(false)}
          onStarted={(job) => {
            setStarting(false);
            flash(`Training job ${shortId(job.id)} ${job.status}.`);
            navigate(`/training/${job.id}`);
          }}
        />
      ) : null}
    </Page>
  );
}

export function TrainingJobPage() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  // The API lists jobs but has no single-job read; find it in the tenant's list (gate 4 for free).
  const jobs = useResource(() => training.list(), []);
  const job = jobs.data?.items.find((j) => j.id === jobId);
  const version = useResource(async () => (job?.model_version_id ? models.get(job.model_version_id) : null), [job?.model_version_id]);
  const crumbs = [{ label: "Home", to: "/home" }, { label: "Training", to: "/training" }, { label: shortId(jobId, 13), mono: true }];

  if (jobs.data && !job) return <NotFoundPage />;
  if (!job) {
    return (
      <Page crumbs={crumbs} kicker="Training job" title={shortId(jobId, 13)}>
        {jobs.error ? <ErrorBanner error={jobs.error} /> : <Skeleton />}
      </Page>
    );
  }
  const active = ACTIVE_STATES.includes(job.status);
  const failed = job.status === "failed";
  const done = job.status === "succeeded";
  const at = jobStageIndex(job.status);
  const v = version.data;
  const metricEntries = v ? Object.entries(v.metrics ?? {}) : [];

  return (
    <Page
      crumbs={crumbs}
      kicker="Training job"
      title={shortId(job.id, 13)}
      badge={<Badge group="job" value={job.status} />}
      subtitle={active ? "The job is running. Refresh to update." : done ? "The job completed and registered a model version. Activation is a separate, deliberate action." : failed ? "The job stopped before producing a version." : undefined}
      actions={[
        { label: "Refresh", onClick: () => void jobs.reload() },
        { label: "Cancel job", disabled: true, reason: active ? "Cancellation is not available in this release." : "Only a job in an active state can be cancelled.", onClick: () => undefined },
      ]}
    >
      <StageRail title="Pipeline stage" stages={JOB_STAGES} at={at} failed={failed} note={failed ? `Stopped: ${job.failure_reason ?? "no reason recorded"}` : done ? "All stages complete." : "Stage in progress."} />
      <DefinitionList
        items={[
          { label: "Requested model type", value: job.model_type, mono: true },
          { label: "Requested at", value: fmtDateTime(job.created_at), mono: true },
          { label: "Completed at", value: fmtDateTime(job.completed_at), mono: true },
          { label: "Dataset snapshot", value: job.dataset_snapshot_id ?? "live data", mono: true, copy: job.dataset_snapshot_id ?? undefined },
          { label: "Produced version", value: v ? <Link to={`/models/${v.id}`}>{v.version_tag}</Link> : job.model_version_id ? shortId(job.model_version_id) : "none", mono: true },
          { label: "Job identifier", value: job.id, mono: true, copy: job.id },
        ]}
      />
      <div className="panels">
        {done && v ? (
          <Panel title="Quality measures" badge={<Badge group="model" value={v.status} />} note={`produced ${v.version_tag}`} body={metricEntries.length ? undefined : "No offline metrics were recorded for this version. Real metrics come from the training worker in a later slice."} dl={metricEntries.map(([k, val]) => ({ label: k, value: typeof val === "number" ? val.toFixed(4) : String(val), mono: true }))} actions={[{ label: `Open model version ${v.version_tag}`, variant: "primary", onClick: () => navigate(`/models/${v.id}`) }]} />
        ) : null}
        {failed ? <Panel title="Failure reason" badge={<Badge group="job" value="failed" />} body={job.failure_reason ?? "No reason was recorded."} /> : null}
        <Panel title="Configuration" body="The configuration the job ran with.">
          <pre className="secret-value" style={{ fontSize: 12.5 }}>
            {JSON.stringify(job.configuration ?? {}, null, 2)}
          </pre>
          {job.qdrant_collection ? (
            <p className="p-body">
              Embedding index: <span className="mono">{job.qdrant_collection}</span>
            </p>
          ) : null}
        </Panel>
      </div>
      <Footnote>Snapshot construction, graph building and indexing are platform processes; they appear here only as stages.</Footnote>
    </Page>
  );
}
