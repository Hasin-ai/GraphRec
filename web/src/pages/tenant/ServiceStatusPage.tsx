import { Link } from "react-router-dom";
import { models, serving } from "../../api";
import { useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDateTime, fmtNumber, fmtPercent } from "../../lib/format";
import { Page } from "../../ui/Page";
import { evaluationModeLabel, formatMetricValue, humanizeKey, modelLabel } from "../../lib/labels";
import { Badge, Banner, DefinitionList, ErrorBanner, FilterBar, IdChip, Panel, PanelTable, Skeleton, Stats } from "../../ui/primitives";
import { ScalingPanel } from "./ScalingPanel";
const WINDOWS: Record<string, number> = { 'last hour': 60, 'last 24 hours': 1440, 'last 7 days': 10080 };
export function ServiceStatusPage() {
  const { can } = useSession();
  const [queryWindow, setSpan] = useQueryState('window', 'last hour');
  const span = queryWindow in WINDOWS ? queryWindow : 'last hour';
  const deployment = useResource(() => serving.deployment(), []);
  const canMetrics = can('metrics:read');
  const metrics = useResource(() => canMetrics ? serving.metrics(WINDOWS[span]) : Promise.resolve(null), [canMetrics, span]);
  const versions = useResource(() => can('models:read') ? models.list() : Promise.resolve(null), [can('models:read')]);
  const d = deployment.data; const m = metrics.data;
  const active = versions.data?.items.find(v => v.id === d?.active_model_version_id);
  const qm = (m?.quality?.metrics ?? {}) as { source?: Record<string, unknown>; validation?: Record<string, unknown> };
  const scores = Object.entries(qm.validation ?? {}).filter(([k, val]) => typeof val === 'number' && /@\d+$/.test(k)) as [string, number][];
  const ks = [...new Set(scores.map(([k]) => k.split('@')[1]))];
  const source = qm.source ?? {};
  const HASH_KEYS = ['data_fingerprint', 'checkpoint_sha256'];
  const details = Object.entries(source).filter(([k]) => !HASH_KEYS.includes(k) && k !== 'artifact' && k !== 'engine_version');
  const items = typeof source.items === 'number' ? source.items : null;
  const indexed = typeof source.indexed_items === 'number' ? source.indexed_items : null;
  const servingUp = d?.status === 'available' && !!d.active_model_version_id;
  const activeLabel = active ? modelLabel(active, versions.data?.items ?? []) : d?.active_model_version_id ? 'the selected model' : null;
  const requests = m?.request_count ?? 0;
  return <Page crumbs={[{ label: 'Home', to: '/home' }, { label: 'Service Status' }]} title="Service Status" subtitle="Serving configuration and measured recommendation traffic." actions={[{ label: 'Refresh', onClick: () => { void deployment.reload(); void metrics.reload(); void versions.reload(); } }]}>
    {deployment.error ? <ErrorBanner error={deployment.error} title="Serving configuration unavailable" onRetry={deployment.reload} /> : null}
    {versions.error ? <ErrorBanner error={versions.error} title="Model labels unavailable" onRetry={versions.reload} /> : null}
    {d ? <section className={`status-head tone-${!servingUp ? 'danger' : canMetrics && requests === 0 ? 'warn' : 'ok'}`}>
      <Badge group="deploy" value={d.status} />
      <h2>{servingUp ? `Serving ${activeLabel}` : 'Not serving recommendations'}</h2>
      <p>{!servingUp ? (d.failure_reason ?? 'No model is active. Activate a version on Model Versions.') : canMetrics ? (requests === 0 ? `Ready, but no recommendation requests in the ${span}.` : `${fmtNumber(requests)} requests in the ${span}.`) : 'A model is loaded and can answer requests.'}{d.last_transition_at ? ` Active since ${fmtDateTime(d.last_transition_at)}.` : ''}</p>
    </section> : null}
    {!d && deployment.loading ? <Skeleton rows={2} /> : d ? <Panel title="Serving configuration">
      <DefinitionList items={[
        { label: 'Serving state', badge: <Badge group="deploy" value={d.status} /> },
        { label: 'Selected model', value: d.active_model_version_id ? can('models:read') ? <Link to={`/models/${d.active_model_version_id}`}>{active ? modelLabel(active, versions.data?.items ?? []) : d.active_model_version_id}</Link> : d.active_model_version_id : 'No active model', copy: active?.version_tag ?? d.active_model_version_id ?? undefined },
        ...(d.desired_model_version_id && d.desired_model_version_id !== d.active_model_version_id ? [{ label: 'Pending model', value: (() => { const v = versions.data?.items.find(x => x.id === d.desired_model_version_id); return v ? modelLabel(v, versions.data?.items ?? []) : d.desired_model_version_id; })() }] : []),
        { label: 'Serving capacity', value: `${d.ready_capacity ?? 0} of ${d.desired_capacity ?? 1} units ready` },
        { label: 'Last activation', value: fmtDateTime(d.last_transition_at) },
      ]} />
      {d.failure_reason ? <Banner tone="danger" title="Serving reported a failure">{d.failure_reason}</Banner> : null}
      <p className="footnote">Serving capacity is logical: each unit adds concurrent recommendation slots that every API process enforces through the shared limiter. It does not start separate serving instances.</p>
    </Panel> : null}
    {canMetrics ? <Panel title="Recommendation traffic">
      <FilterBar filters={[{ id: 'window', label: 'Measurement window', value: span, onChange: setSpan, options: Object.keys(WINDOWS) }]} onClear={() => setSpan('last hour')} />
      {metrics.error ? <ErrorBanner error={metrics.error} title="Traffic measurements unavailable" onRetry={metrics.reload} /> : null}
      {!m && metrics.loading ? <Skeleton rows={2} /> : m ? <>
        <Stats items={[
          { label: 'Requests', value: fmtNumber(m.request_count), note: `${m.request_rate.toFixed(2)} per minute` },
          { label: 'p95 latency', value: m.p95_latency_ms === null ? '—' : `${fmtNumber(m.p95_latency_ms)} ms`, note: 'Successful requests' },
          { label: 'Fallback rate', value: m.fallback_rate === null ? '—' : fmtPercent(m.fallback_rate), note: 'Served without the model' },
          { label: 'Error rate', value: m.error_rate === null ? '—' : fmtPercent(m.error_rate), tone: m.error_rate ? 'warn' : undefined },
        ]} />
        {m.request_count === 0 ? <Banner tone="info" title="No requests in this window">Rates and latency will appear after recommendation requests are recorded. You can also choose a wider measurement window.</Banner> : null}
        <p className="footnote">{fmtDateTime(m.window_start)} – {fmtDateTime(m.window_end)}. Rates use this tenant's recorded requests.</p>
      </> : null}
    </Panel> : <p className="footnote">Your session does not include access to serving metrics.</p>}
    {d?.rate_limiter ? <Panel title="Rate limiting" note={d.rate_limiter.status === 'ok' ? 'Healthy' : 'Needs attention'}>
      {d.rate_limiter.status === 'degraded' ? <Banner tone="warn" title="Rate-limit store unavailable">Redis is not responding. Recommendations are still served, and limits are enforced separately by each API process until Redis recovers.</Banner> : null}
      <DefinitionList items={[
        { label: 'Rate-limit store', badge: <Badge group="platform" value={d.rate_limiter.status === 'ok' ? 'healthy' : d.rate_limiter.status} />, value: d.rate_limiter.backend === 'redis' ? 'Redis' : d.rate_limiter.backend },
        { label: 'Requests let through while the store was down', value: fmtNumber(d.rate_limiter.fail_open_total) },
        { label: 'Last store error', value: d.rate_limiter.last_error_at ? fmtDateTime(d.rate_limiter.last_error_at) : 'None' },
      ]} />
    </Panel> : null}
    <ScalingPanel />
    {m?.quality ? <Panel title="Model quality and details" note={activeLabel ?? m.quality.version_tag} body={<>Offline measurements recorded {fmtDateTime(m.quality.recorded_at)}. They describe the model, not live traffic. {qm.validation?.mode ? <>{evaluationModeLabel(qm.validation.mode)}{typeof qm.validation.evaluated_examples === 'number' ? `, ${formatMetricValue('evaluated_examples', qm.validation.evaluated_examples)} examples` : ''}.</> : null}</>}>
      {items !== null && indexed !== null && indexed < items ? <div className="callout warn"><p><strong>{fmtNumber(items - indexed)} of {fmtNumber(items)} items are not in the embedding index.</strong> They can't be recommended by this model until it is retrained or re-indexed.</p></div> : null}
      {scores.length ? <PanelTable columns={['Cut-off', ...['Hit', 'NDCG'].map(label => ({ label, align: 'right' as const }))]} rows={ks.map(k => <tr key={k}><td>Top {k}</td>{['Hit', 'NDCG'].map(name => { const hit = scores.find(([key]) => key === `${name}@${k}`); return <td key={name} className="num">{hit ? hit[1].toFixed(4) : '—'}</td>; })}</tr>)} /> : <p className="p-body">No offline quality measurements were recorded for this version.</p>}
      {details.length ? <dl className="kv-grid">{details.map(([k, val]) => <div key={k}><dt>{humanizeKey(k)}</dt><dd>{formatMetricValue(k, val)}</dd></div>)}</dl> : null}
      {source.artifact || HASH_KEYS.some(k => typeof source[k] === 'string') ? <div className="row small muted">{typeof source.artifact === 'string' ? <>Checkpoint <IdChip value={source.artifact} length={40} label="Checkpoint" /></> : null}{typeof source.engine_version === 'string' ? <>Engine <IdChip value={source.engine_version} length={24} label="Engine version" /></> : null}{HASH_KEYS.map(k => typeof source[k] === 'string' ? <span key={k}>{humanizeKey(k)} <IdChip value={source[k] as string} length={10} label={humanizeKey(k)} /></span> : null)}</div> : null}
    </Panel> : null}
  </Page>;
}
