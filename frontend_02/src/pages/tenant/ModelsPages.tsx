import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { models, training } from "../../api";
import { isApiError } from "../../api/client";
import type { ModelVersionResource } from "../../api/types";
import { useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, shortId, flattenMetrics } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Field, Select } from "../../ui/Form";
import { Page, type HeaderAction } from "../../ui/Page";
import { ActionsCell, Badge, Cell, DataTable, DefinitionList, ErrorBanner, FilterBar, Footnote, Panel, PanelTable, Skeleton, Banner } from "../../ui/primitives";
import { NotFoundPage } from "../errors/ErrorPages";

const STATUSES = ["eligible", "active", "retired", "archived"];

function metricSummary(v: ModelVersionResource): string {
  const entries = flattenMetrics(v.metrics).filter(([k, val]) => typeof val === "number" && /(hit|ndcg)@/i.test(k)) as [string, number][];
  if (!entries.length) return "no offline metrics";
  return entries
    .slice(0, 2)
    .map(([k, val]) => `${k} ${val.toFixed(3)}`)
    .join(" · ");
}

function ActivateDialog({ version, active, onClose, onDone }: { version: ModelVersionResource; active?: ModelVersionResource; onClose: () => void; onDone: (v: ModelVersionResource) => void }) {
  return (
    <Dialog
      title={`Activate ${version.version_tag}`}
      width={640}
      confirmLabel={`Activate ${version.version_tag}`}
      body={`${version.version_tag} will be selected for recommendation requests for this tenant.`}
      consequence={active ? `${active.version_tag} is retired and retained as a roll-back target.` : "This selects the first active model. Request metrics are available on Service Status."}
      facts={[
        { label: "Model type", value: version.model_type },
        { label: "Current active", value: active ? active.version_tag : "none" },
        { label: "Created", value: fmtDateTime(version.created_at) },
        { label: "Metrics", value: metricSummary(version) },
      ]}
      onConfirm={async () => onDone(await models.activate(version.id))}
      onClose={onClose}
    />
  );
}

export function ModelsPage() {
  const { can } = useSession();
  const { flash } = useToast();
  const navigate = useNavigate();
  const versions = useResource(() => models.list(), []);
  const [status, setStatus] = useQueryState("status", "all statuses");
  const [activating, setActivating] = useState<ModelVersionResource | null>(null);
  const items = versions.data?.items ?? [];
  const list = items.filter((v) => status === "all statuses" || v.status === status);
  const active = items.find((v) => v.status === "active");
  const canDeploy = can("models:deploy");

  const rows = list.map((v) => (
    <tr key={v.id}>
      <td>
        <Link to={`/models/${v.id}`} className="td-mono">
          {v.version_tag}
        </Link>
      </td>
      <Cell mono>{v.model_type}</Cell>
      <td>
        <Badge group="model" value={v.status} />
      </td>
      <Cell mono>{fmtDateTime(v.created_at)}</Cell>
      <Cell mono muted>
        {metricSummary(v)}
      </Cell>
      <ActionsCell
        actions={[
          { label: "Open", onClick: () => navigate(`/models/${v.id}`) },
          { label: "Activate", disabled: v.status !== "eligible" || !canDeploy, reason: !canDeploy ? "Requires models:deploy." : v.status === "active" ? "Already active." : v.status === "eligible" ? undefined : "Only an eligible version can be activated.", onClick: () => setActivating(v) },
        ]}
      />
    </tr>
  ));

  return (
    <Page crumbs={[{ label: "Home", to: "/home" }, { label: "Model Versions" }]} kicker="Model lifecycle" title="Model Versions" subtitle="Every succeeded training job registers a version. A version serves traffic only once it is deliberately activated.">
      {versions.error ? <ErrorBanner error={versions.error} onRetry={versions.reload} /> : null}
      {versions.data ? <p className="model-summary">Active model: {active ? <Link className="mono" to={`/models/${active.id}`}>{active.version_tag}</Link> : 'None selected'}</p> : null}
      <FilterBar filters={[{ id: "status", label: "Lifecycle status", value: status, onChange: setStatus, options: ["all statuses", ...STATUSES] }]} onClear={() => setStatus("all statuses")} />
      {!versions.data ? (versions.loading ? <Skeleton /> : null) : (
        <DataTable minWidth={850} columns={["Version", "Model type", "Lifecycle status", "Created at", "Quality summary", { label: "", align: "right" }]} rows={rows} count={`${list.length} of ${items.length}`} empty={{ title: status === "all statuses" ? "No model versions yet" : "No versions match this filter", body: status === "all statuses" ? "Prepare a model to produce your first version." : "Choose another status or clear the filter.", action: can("training:read") ? { label: "Go to training", onClick: () => navigate("/training") } : undefined }} />
      )}
      {activating ? (
        <ActivateDialog
          version={activating}
          active={active}
          onClose={() => setActivating(null)}
          onDone={(v) => {
            setActivating(null);
            flash(`${v.version_tag} activated.`);
            void versions.reload();
          }}
        />
      ) : null}
    </Page>
  );
}

export function ModelVersionPage() {
  const { versionId = "" } = useParams();
  return <ModelVersionDetail key={versionId} />;
}

function ModelVersionDetail() {
  const { versionId = "" } = useParams();
  const { can } = useSession();
  const { flash } = useToast();
  const navigate = useNavigate();
  const version = useResource(() => models.get(versionId), [versionId]);
  const all = useResource(() => models.list(), [versionId]);
  const jobs = useResource(() => can("training:read") ? training.list() : Promise.resolve(null), [versionId, can("training:read")]);
  const [dialog, setDialog] = useState<"activate" | "rollback" | "archive" | null>(null);
  const [target, setTarget] = useState("");

  const crumbs = [{ label: "Home", to: "/home" }, { label: "Model Versions", to: "/models" }, { label: shortId(versionId), mono: true }];
  if (version.error && isApiError(version.error) && (version.error.status === 404 || version.error.status === 422)) return <NotFoundPage />;
  if (!version.data) {
    return (
      <Page crumbs={crumbs} kicker="Model version" title={shortId(versionId)}>
        {version.error ? <ErrorBanner error={version.error} onRetry={version.reload} /> : <Skeleton />}
      </Page>
    );
  }
  const v = version.data;
  const items = all.data?.items ?? [];
  const active = items.find((x) => x.status === "active");
  const retired = items.filter((x) => x.status === "retired");
  const producingJob = jobs.data?.items.find((j) => j.model_version_id === v.id);
  const canDeploy = can("models:deploy");
  const canWrite = can("models:write");
  const canActivate = v.status === "eligible" && canDeploy && !!all.data && !all.error;
  const canRollback = v.status === "active" && retired.length > 0 && canDeploy && !all.error;
  const protectedRollback = retired.slice().sort((a, b) => (b.activated_at ?? b.created_at).localeCompare(a.activated_at ?? a.created_at))[0]?.id;
  const canArchive = v.status !== "active" && v.status !== "archived" && !(active && v.id === protectedRollback) && canWrite;
  const metricEntries = flattenMetrics(v.metrics).filter(([key, value]) => typeof value === 'number' && !key.startsWith('source.') && !key.startsWith('training.'));
  const activeMetrics = active && active.id !== v.id ? Object.fromEntries(flattenMetrics(active.metrics)) : null;

  return (
    <Page
      crumbs={[crumbs[0], crumbs[1], { label: v.version_tag, mono: true }]}
      kicker="Model version"
      title={v.version_tag}
      badge={<Badge group="model" value={v.status} />}
      subtitle={v.status === "active" ? "This version is selected for recommendation requests." : producingJob ? `Registered by job ${shortId(producingJob.id)}.` : undefined}
      actions={([
        { label: "Activate", variant: "primary", disabled: !canActivate, reason: canActivate ? undefined : !canDeploy ? "Requires models:deploy." : v.status === "active" ? "This version is already active." : !all.data || all.error ? "Load the model registry before activating." : "Only an eligible version can be activated.", onClick: () => setDialog("activate") },
        { label: "Roll back", disabled: !canRollback, reason: canRollback ? undefined : !canDeploy ? "Requires models:deploy." : "Roll back applies to the active version, and requires a retired target.", onClick: () => { setTarget(retired[0]?.id ?? ""); setDialog("rollback"); } },
        { label: "Archive", disabled: !canArchive, reason: canArchive ? undefined : !canWrite ? "Requires models:write." : v.status === "active" ? "An active version cannot be archived." : active && v.id === protectedRollback ? "This version is retained as the rollback target." : "Already archived.", onClick: () => setDialog("archive") },
      ] as HeaderAction[]).filter(action => action.label === 'Activate' ? v.status === 'eligible' : action.label === 'Archive' ? v.status !== 'active' && v.status !== 'archived' : v.status === 'active')}
    >
      {version.error ? <ErrorBanner error={version.error} onRetry={version.reload} /> : null}
      {all.error ? <ErrorBanner error={all.error} title="Model registry unavailable" onRetry={all.reload} /> : null}
      {jobs.error ? <ErrorBanner error={jobs.error} title="Training source unavailable" onRetry={jobs.reload} /> : null}
      {producingJob && !producingJob.configuration?.pretrained_artifact && producingJob.configuration?.mode !== 'train' ? <Banner tone="warn" title="Development placeholder">This version was created with synthetic embeddings. It has no trained-model quality measurements.</Banner> : null}
      <DefinitionList
        items={[
          { label: "Model type", value: v.model_type, mono: true },
          { label: "Created at", value: fmtDateTime(v.created_at), mono: true },
          { label: "Activated at", value: fmtDateTime(v.activated_at), mono: true },
          { label: "Version identifier", value: v.id, mono: true, copy: v.id },
        ]}
      />
      <div className="panels">
        <Panel title="Quality against the active version" body={metricEntries.length ? "Comparison is the input to the activation decision." : "No offline metrics were recorded for this version. Versions imported from a DGSR checkpoint carry the checkpoint's validation Hit@k and NDCG@k; placeholder training records none."}>
          {metricEntries.length ? (
            <PanelTable
              columns={["Measure", "This version", active && active.id !== v.id ? `Active ${active.version_tag}` : "Active", "Δ active"]}
              rows={metricEntries.map(([k, val]) => {
                const mine = typeof val === "number" ? val : null;
                const theirs = activeMetrics && typeof activeMetrics[k] === "number" ? (activeMetrics[k] as number) : null;
                return (
                  <tr key={k}>
                    <Cell>{k}</Cell>
                    <Cell mono>{mine === null ? String(val) : mine.toFixed(4)}</Cell>
                    <Cell mono>{theirs === null ? "—" : theirs.toFixed(4)}</Cell>
                    <Cell mono>{mine !== null && theirs !== null ? `${mine - theirs >= 0 ? "+" : ""}${(mine - theirs).toFixed(4)}` : "—"}</Cell>
                  </tr>
                );
              })}
            />
          ) : null}
        </Panel>
        <Panel
          title="Artifact and index"
          dl={[
            { label: "Artifact", value: v.artifact_uri ?? "—", mono: true, copy: v.artifact_uri ?? undefined },
            { label: "Embedding index", value: v.qdrant_collection ?? producingJob?.qdrant_collection ?? "not recorded on the version", mono: true },
            { label: "Producing job", value: producingJob ? <Link to={`/training/${producingJob.id}`}>{shortId(producingJob.id, 13)}</Link> : "—", mono: true },
            { label: "Dataset snapshot", value: producingJob?.dataset_snapshot_id ? shortId(producingJob.dataset_snapshot_id, 13) : "—", mono: true },
          ]}
        />
      </div>
      <Footnote>Roll back re-activates a retired version through the same activation path; if it fails, the current version stays active.</Footnote>

      {dialog === "activate" ? (
        <ActivateDialog
          version={v}
          active={active}
          onClose={() => setDialog(null)}
          onDone={(updated) => {
            setDialog(null);
            version.setData(updated);
            flash(`${updated.version_tag} activated.`);
            void all.reload();
          }}
        />
      ) : null}
      {dialog === "rollback" ? (
        <Dialog
          title={`Roll back from ${v.version_tag}`}
          width={640}
          confirmLabel="Roll back"
          body="Serving returns to a retired version. The target is activated and this version is retired."
          consequence={`If the target fails, ${v.version_tag} remains active.`}
          onConfirm={async () => {
            if (!target) return "No retired version is available as a roll-back target.";
            const restored = await models.rollback(target);
            setDialog(null);
            flash(`Rolled back to ${restored.version_tag}.`);
            navigate("/models");
          }}
          onClose={() => setDialog(null)}
        >
          <Field id="d-target" label="Roll-back target">
            <Select id="d-target" value={target} onChange={setTarget} options={retired.map((r) => ({ value: r.id, label: `${r.version_tag} · ${fmtDateTime(r.created_at)}` }))} />
          </Field>

        </Dialog>
      ) : null}
      {dialog === "archive" ? (
        <Dialog
          title={`Archive ${v.version_tag}`}
          confirmLabel="Archive"
          body="An archived version is retained for audit and is excluded from activation and roll-back choices in this console. The backend also attempts to delete its embedding index."
          consequence="This action cannot be undone from the console."
          onConfirm={async () => {
            const archived = await models.archive(v.id);
            setDialog(null);
            flash(`${archived.version_tag} archived.`);
            navigate("/models");
          }}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </Page>
  );
}
