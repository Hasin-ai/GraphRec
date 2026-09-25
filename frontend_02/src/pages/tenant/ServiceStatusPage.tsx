import { Link } from "react-router-dom";
import { models, serving } from "../../api";
import { useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { flattenMetrics, fmtDateTime, fmtNumber, fmtPercent } from "../../lib/format";
import { Page } from "../../ui/Page";
import { Badge, Banner, DefinitionList, ErrorBanner, FilterBar, Panel, Skeleton, Stats } from "../../ui/primitives";
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
  const quality = m?.quality ? flattenMetrics(m.quality.metrics) : [];
  return <Page crumbs={[{ label: 'Home', to: '/home' }, { label: 'Service Status' }]} title="Service Status" subtitle="Serving configuration and measured recommendation traffic." actions={[{ label: 'Refresh', onClick: () => { void deployment.reload(); void metrics.reload(); void versions.reload(); } }]}>
    {deployment.error ? <ErrorBanner error={deployment.error} title="Serving configuration unavailable" onRetry={deployment.reload} /> : null}
    {versions.error ? <ErrorBanner error={versions.error} title="Model labels unavailable" onRetry={versions.reload} /> : null}
    {!d && deployment.loading ? <Skeleton rows={2} /> : d ? <Panel title="Serving configuration">
      <DefinitionList items={[
        { label: 'API-reported state', badge: <Badge group="deploy" value={d.status} /> },
        { label: 'Selected model', value: d.active_model_version_id ? can('models:read') ? <Link to={`/models/${d.active_model_version_id}`}>{active?.version_tag ?? d.active_model_version_id}</Link> : d.active_model_version_id : 'No active model', mono: true, copy: d.active_model_version_id ?? undefined },
        { label: 'Last activation', value: fmtDateTime(d.last_transition_at) },
      ]} />
      <p className="footnote">This state reports model activation, not a live dependency health check. {d.failure_reason ?? ''}</p>
    </Panel> : null}
    {canMetrics ? <Panel title="Recommendation traffic">
      <FilterBar filters={[{ id: 'window', label: 'Measurement window', value: span, onChange: setSpan, options: Object.keys(WINDOWS) }]} onClear={() => setSpan('last hour')} />
      {metrics.error ? <ErrorBanner error={metrics.error} title="Traffic measurements unavailable" onRetry={metrics.reload} /> : null}
      {!m && metrics.loading ? <Skeleton rows={2} /> : m ? <>
        <Stats items={[
          { label: 'Requests', value: fmtNumber(m.request_count), note: `${m.request_rate.toFixed(2)} per minute` },
          { label: 'Latency p95', value: m.p95_latency_ms === null ? 'Not available' : `${fmtNumber(m.p95_latency_ms)} ms`, note: 'Successful requests' },
          { label: 'Fallback rate', value: m.fallback_rate === null ? 'Not available' : fmtPercent(m.fallback_rate) },
          { label: 'Error rate', value: m.error_rate === null ? 'Not available' : fmtPercent(m.error_rate), tone: m.error_rate ? 'warn' : undefined },
        ]} />
        {m.request_count === 0 ? <Banner tone="info" title="No requests in this window">Rates and latency will appear after recommendation requests are recorded. You can also choose a wider measurement window.</Banner> : null}
        <p className="footnote">{fmtDateTime(m.window_start)} – {fmtDateTime(m.window_end)}. Rates use this tenant's recorded requests.</p>
      </> : null}
    </Panel> : <p className="footnote">Your session does not include access to serving metrics.</p>}
    {m?.quality ? <Panel title="Recorded model quality" note={m.quality.version_tag} body={quality.length ? `Offline measurements recorded ${fmtDateTime(m.quality.recorded_at)}. These describe the model, not live traffic.` : 'No offline quality measurements were recorded for this version.'} dl={quality.map(([key, value]) => ({ label: key, value: typeof value === 'number' ? value.toFixed(4) : String(value), mono: true }))} /> : null}
  </Page>;
}
