import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { models, training } from "../../api";
import { isApiError } from "../../api/client";
import type { ModelVersionResource } from "../../api/types";
import { useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, fmtDateTimeFull, shortId, flattenMetrics } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Field, Select } from "../../ui/Form";
import { Page, type HeaderAction } from "../../ui/Page";
import { Badge, Cell, DataTable, DefinitionList, ErrorBanner, FilterBar, Footnote, IdChip, Panel, PanelTable, Skeleton, StatusLegend, Banner } from "../../ui/primitives";
import { NotFoundPage } from "../errors/ErrorPages";
import { evaluationModeLabel, formatMetricValue, humanizeKey, modelLabel, modelTypeLabel } from "../../lib/labels";

const STATUSES = ["eligible", "active", "retired", "archived"];

const metric = (v: ModelVersionResource, key: string): number | null => {
  const value = (v.metrics as { validation?: Record<string, unknown> } | null)?.validation?.[key];
  return typeof value === "number" ? value : null;
};
const STATUS_HELP_MODEL: Record<string, string> = { eligible: "Ready to activate.", active: "Serving now.", retired: "Rollback target.", archived: "Audit only; cannot serve." };
const STATUS_ORDER: Record<string, number> = { active: 0, eligible: 1, retired: 2, archived: 3 };
/** A signature of the offline scores; equal signatures mean "same checkpoint, same numbers". */
const scoreSignature = (v: ModelVersionResource) => JSON.stringify((v.metrics as { validation?: unknown } | null)?.validation ?? null);
const checkpointOf = (v: ModelVersionResource) => { const src = (v.metrics as { source?: { artifact?: unknown } } | null)?.source; return typeof src?.artifact === "string" ? src.artifact : null; };

function useTenantEmailDomain(): string | null {
  const { tenant } = useSession();
  const domain = tenant?.email?.split("@")[1]?.split(".")[0];
  return domain ? domain.replace(/[-_]+/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : null;
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
        { label: "Model type", value: modelTypeLabel(version.model_type) },
        { label: "Current active", value: active ? active.version_tag : "none" },
        { label: "Created", value: fmtDateTime(version.created_at) },
        { label: "Hit@10 · NDCG@10", value: `${metric(version, "Hit@10")?.toFixed(3) ?? "—"} · ${metric(version, "NDCG@10")?.toFixed(3) ?? "—"}` },
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

  const ordered = list.slice().sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) || Date.parse(b.created_at) - Date.parse(a.created_at));
  const byAge = items.slice().sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  const vNum = (v: ModelVersionResource) => byAge.findIndex(x => x.id === v.id) + 1;
  // Rollback context: the active version is older than a version that was activated later.
  const rolledBackFrom = active ? items.filter(x => x.id !== active.id && x.activated_at && Date.parse(x.created_at) > Date.parse(active.created_at)).sort((a, b) => Date.parse(b.activated_at!) - Date.parse(a.activated_at!))[0] : undefined;
  const identicalScores = items.length > 1 && items.every(x => scoreSignature(x) === scoreSignature(items[0])) && scoreSignature(items[0]) !== "null";
  const sharedCheckpoint = identicalScores ? checkpointOf(items[0]) : null;
  const types = [...new Set(items.map(v => modelTypeLabel(v.model_type)))];
  const workspace = (useTenantEmailDomain() ?? "");
  const canTrain = can("training:write");
  const scoreCell = (v: ModelVersionResource, key: string) => {
    const mine = metric(v, key);
    if (mine === null) return <span className="td-muted">—</span>;
    const base = active && active.id !== v.id ? metric(active, key) : null;
    const diff = base === null ? null : mine - base;
    return <>{mine.toFixed(3)}{diff !== null && Math.abs(diff) >= 0.0005 ? <span className={`delta ${diff > 0 ? "up" : "down"}`}>{diff > 0 ? "+" : ""}{diff.toFixed(3)} vs serving</span> : null}</>;
  };
  const go = (v: ModelVersionResource) => navigate(`/models/${v.id}`);

  const rows = ordered.map((v) => (
    <tr key={v.id} className={`reg-row${v.status === "active" ? " row-highlight" : ""}`} onClick={e => { if (!(e.target as HTMLElement).closest("a,button")) go(v); }}>
      <td>
        <div className="ver-cell">
          <span className="ver"><Link to={`/models/${v.id}`} aria-label={`Version ${vNum(v)} details`}>v{vNum(v)}</Link></span>
          <span className="ver-meta">{modelTypeLabel(v.model_type)} · <IdChip value={v.version_tag} length={22} label="Version ID" /></span>
          {v.status === "active" && rolledBackFrom ? <span className="rollback-pill" title={`Activated ${fmtDateTime(v.activated_at)}`}>↩ Rolled back from v{vNum(rolledBackFrom)} · {fmtDateTime(v.activated_at)}</span> : null}
        </div>
      </td>
      <td><Badge group="model" value={v.status} /></td>
      <td className="num" data-label="Hit@10">{scoreCell(v, "Hit@10")}</td>
      <td className="num" data-label="NDCG@10">{scoreCell(v, "NDCG@10")}</td>
      <td data-hide-mobile><time dateTime={v.created_at} title={fmtDateTimeFull(v.created_at)}>{fmtDateTime(v.created_at)}</time></td>
      <td className="right">
        {v.status === "eligible" ? (canDeploy ? <button type="button" className="btn btn-primary btn-sm" onClick={() => setActivating(v)}>Activate</button> : <span className="td-muted small" title="Your role cannot activate models.">Ready</span>)
          : v.status === "retired" && active ? (canDeploy ? <Link className="btn btn-secondary btn-sm" to={`/models/${active.id}?rollback=${v.id}`}>Roll back…</Link> : <span className="td-muted small">Rollback available</span>)
          : <Link className="btn btn-ghost btn-sm" to={`/models/${v.id}`}>Details</Link>}
      </td>
    </tr>
  ));

  return (
    <Page crumbs={[{ label: "Home", to: "/home" }, { label: "Model Versions" }]} kicker="Model registry" title="Model Versions"
      subtitle={items.length ? <span className="reg-head"><strong>{types.join(", ") || "Model"}{workspace ? ` · ${workspace}` : ""}</strong><span>{items.length} {items.length === 1 ? "version" : "versions"} · {active ? `v${vNum(active)} serving` : "none serving"}</span></span> : "Each training run registers a version. Exactly one version serves at a time."}
      actions={canTrain ? [{ label: "+ Train new version", variant: "primary", onClick: () => navigate("/training") }] : can("training:read") ? [{ label: "Training", onClick: () => navigate("/training") }] : []}>
      {versions.error ? <ErrorBanner error={versions.error} onRetry={versions.reload} /> : null}
      {versions.data && !active && items.length ? <div className="callout warn" role="status"><p><strong>No version is serving.</strong> Activate a version that is ready to start answering recommendation requests.</p></div> : null}
      {items.length > 4 ? <FilterBar filters={[{ id: "status", label: "Status", value: status, onChange: setStatus, options: ["all statuses", ...STATUSES] }]} onClear={() => setStatus("all statuses")} /> : null}
      {!versions.data ? (versions.loading ? <Skeleton /> : null) : (
        <div className="table-mobile-cards"><DataTable minWidth={760} columns={["Version", "Status", { label: "Hit@10", align: "right" }, { label: "NDCG@10", align: "right" }, "Created", { label: "", align: "right" }]} rows={rows} empty={{ title: status === "all statuses" ? "No model versions yet" : "No versions match this filter", body: status === "all statuses" ? "Train or import a model to produce your first version." : "Choose another status or clear the filter.", action: can("training:read") ? { label: "Go to training", onClick: () => navigate("/training") } : undefined }} /></div>
      )}
      {items.length ? <p className="footnote">Scores are offline validation results (higher is better){(() => { const mode = (items[0].metrics as { validation?: { mode?: unknown; evaluated_examples?: unknown } } | null)?.validation; return mode?.mode ? `: ${evaluationModeLabel(mode.mode).toLowerCase()}${typeof mode.evaluated_examples === "number" ? `, ${formatMetricValue("evaluated_examples", mode.evaluated_examples)} examples` : ""}` : ""; })()}. Differences are shown against the serving version.</p> : null}
      {identicalScores ? <div className="compact-note"><span className="i" aria-hidden="true">i</span><p><strong>All versions were imported from the same checkpoint{sharedCheckpoint ? <> (<code className="inline-code">{sharedCheckpoint}</code>)</> : null}.</strong> Their evaluation metrics are therefore identical. Train on new data or import a different checkpoint to produce a distinct version.</p></div> : null}
      {items.length ? <details className="details-section legend-details"><summary>Status definitions</summary><StatusLegend group="model" values={STATUSES} /></details> : null}
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
  const [search, setSearch] = useSearchParams();
  const requestedRollback = search.get("rollback");

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
  const metricEntries = flattenMetrics(v.metrics).filter(([key, value]) => typeof value === 'number' && key.startsWith('validation.') && /@\d+$/.test(key));
  const validation = (v.metrics as { validation?: Record<string, unknown> } | null)?.validation ?? {};
  const compare = !!active && active.id !== v.id;
  const checkpoint = checkpointOf(v);
  const activeMetrics = active && active.id !== v.id ? Object.fromEntries(flattenMetrics(active.metrics)) : null;

  return (
    <Page
      crumbs={[crumbs[0], crumbs[1], { label: all.data ? modelLabel(v, all.data.items) : v.version_tag }]}
      kicker="Model version"
      title={all.data ? modelLabel(v, all.data.items) : modelTypeLabel(v.model_type) + " model"}
      badge={<Badge group="model" value={v.status} />}
      subtitle={<><code className="inline-code">{v.version_tag}</code> · {v.status === "active" ? "Selected for recommendation requests." : producingJob ? "Registered by a training run." : "Registered model version."}</>}
      actions={([
        { label: "Activate", variant: "primary", disabled: !canActivate, reason: canActivate ? undefined : !canDeploy ? "Your role cannot activate models." : v.status === "active" ? "This version is already active." : !all.data || all.error ? "Load the model registry before activating." : "Only an eligible version can be activated.", onClick: () => setDialog("activate") },
        { label: "Roll back", disabled: !canRollback, reason: canRollback ? undefined : !canDeploy ? "Your role cannot activate models." : "Roll back applies to the active version, and requires a retired target.", onClick: () => { setTarget(retired[0]?.id ?? ""); setDialog("rollback"); } },
        { label: "Archive", disabled: !canArchive, reason: canArchive ? undefined : !canWrite ? "Your role cannot archive models." : v.status === "active" ? "An active version cannot be archived." : active && v.id === protectedRollback ? "This version is retained as the rollback target." : "Already archived.", onClick: () => setDialog("archive") },
      ] as HeaderAction[]).filter(action => action.label === 'Activate' ? v.status === 'eligible' : action.label === 'Archive' ? v.status !== 'active' && v.status !== 'archived' : v.status === 'active')}
    >
      {version.error ? <ErrorBanner error={version.error} onRetry={version.reload} /> : null}
      {all.error ? <ErrorBanner error={all.error} title="Model registry unavailable" onRetry={all.reload} /> : null}
      {jobs.error ? <ErrorBanner error={jobs.error} title="Training source unavailable" onRetry={jobs.reload} /> : null}
      {producingJob && !producingJob.configuration?.pretrained_artifact && producingJob.configuration?.mode !== 'train' ? <Banner tone="warn" title="Development placeholder">This version was created with synthetic embeddings. It has no trained-model quality measurements.</Banner> : null}
      <DefinitionList
        items={[
          { label: "Model type", value: modelTypeLabel(v.model_type) },
          { label: "Version tag", value: v.version_tag, mono: true, copy: v.version_tag },
          { label: "Status", badge: <Badge group="model" value={v.status} />, value: STATUS_HELP_MODEL[v.status] },
          { label: "Created", value: fmtDateTime(v.created_at) },
          { label: "Activated", value: v.activated_at ? fmtDateTime(v.activated_at) : "Never" },
          { label: "Internal ID", value: v.id, mono: true, copy: v.id },
        ]}
      />
      <div className="panels">
        <Panel title={compare ? "Quality compared with the active version" : "Offline quality"} body={metricEntries.length ? <>{compare ? "Use the difference to decide whether to activate this version. " : ""}Evaluated on {formatMetricValue("evaluated_examples", validation.evaluated_examples)} examples. {evaluationModeLabel(validation.mode)}.</> : "No offline metrics were recorded for this version. Versions imported from a DGSR checkpoint carry the checkpoint's validation Hit@k and NDCG@k; placeholder training records none."}>
          {metricEntries.length ? (
            <PanelTable
              columns={compare ? ["Measure", { label: "This version", align: "right" }, { label: `Active (${all.data ? modelLabel(active!, all.data.items).split(" · ")[1] : "current"})`, align: "right" }, { label: "Difference", align: "right" }] : ["Measure", { label: "Score", align: "right" }]}
              rows={metricEntries.map(([k, val]) => {
                const mine = typeof val === "number" ? val : null;
                const theirs = activeMetrics && typeof activeMetrics[k] === "number" ? (activeMetrics[k] as number) : null;
                const diff = mine !== null && theirs !== null ? mine - theirs : null;
                return (
                  <tr key={k}>
                    <Cell>{humanizeKey(k)}</Cell>
                    <td className="num">{mine === null ? String(val) : mine.toFixed(4)}</td>
                    {compare ? <td className="num">{theirs === null ? "—" : theirs.toFixed(4)}</td> : null}
                    {compare ? <td className={`num${diff ? diff > 0 ? " pos" : " neg" : ""}`}>{diff === null ? "—" : Math.abs(diff) < 5e-5 ? "Same" : `${diff > 0 ? "+" : ""}${diff.toFixed(4)}`}</td> : null}
                  </tr>
                );
              })}
            />
          ) : null}
        </Panel>
        <Panel
          title="Artifact and index"
          dl={[
            { label: "Checkpoint", value: checkpoint ? <IdChip value={checkpoint} length={40} label="Checkpoint" /> : v.artifact_uri ? <IdChip value={v.artifact_uri} length={28} label="Artifact" /> : "Not recorded" },
            { label: "Embedding index", value: v.qdrant_collection ?? producingJob?.qdrant_collection ?? <span className="td-muted">Not recorded</span>, mono: !!(v.qdrant_collection ?? producingJob?.qdrant_collection) },
            { label: "Training run", value: producingJob ? <Link to={`/training/${producingJob.id}`}>View run <span className="mono muted">{shortId(producingJob.id)}</span></Link> : "—" },
            { label: "Dataset snapshot", value: producingJob?.dataset_snapshot_id ? <IdChip value={producingJob.dataset_snapshot_id} label="Snapshot ID" /> : "—" },
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
      {dialog === "rollback" || (dialog === null && requestedRollback && canRollback) ? (
        <Dialog
          title={`Roll back from ${all.data ? modelLabel(v, all.data.items) : v.version_tag}`}
          width={640}
          confirmLabel="Confirm rollback"
          body={`${all.data ? modelLabel(v, all.data.items) : v.version_tag} stops serving and the version you choose becomes the active recommendation model. Production recommendations change immediately.`}
          consequence={`If the target fails to load, ${all.data ? modelLabel(v, all.data.items) : v.version_tag} keeps serving.`}
          facts={[{ label: "Serving now", value: all.data ? modelLabel(v, all.data.items) : v.version_tag }, { label: "Roll back to", value: (() => { const t = retired.find(r => r.id === (target || requestedRollback)); return t ? (all.data ? modelLabel(t, all.data.items) : t.version_tag) : "Choose below"; })() }]}
          onConfirm={async () => {
            const chosen = target || requestedRollback || "";
            if (!chosen) return "No retired version is available as a roll-back target.";
            const restored = await models.rollback(chosen);
            setDialog(null);
            flash(`Rolled back to ${restored.version_tag}.`);
            navigate("/models");
          }}
          onClose={() => { setDialog(null); if (requestedRollback) setSearch({}, { replace: true }); }}
        >
          <Field id="d-target" label="Roll-back target">
            <Select id="d-target" value={target || requestedRollback || ""} onChange={setTarget} options={retired.map((r) => ({ value: r.id, label: `${all.data ? modelLabel(r, all.data.items) : r.version_tag} · ${fmtDateTime(r.created_at)}` }))} />
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
