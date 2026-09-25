import { Link } from "react-router-dom";
import { billing, models, products, serving, training } from "../../api";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDateTime, fmtNumber, humanize } from "../../lib/format";
import { quotaState } from "../../lib/quota";
import { Page } from "../../ui/Page";
import { Badge, Banner, ErrorBanner, Panel, Skeleton } from "../../ui/primitives";

export function HomePage() {
  const { can } = useSession();
  const catalog = useResource(() => can('catalog:read') ? products.list({ limit: 1 }) : Promise.resolve(null), [can('catalog:read')], { watch: ['/products', '/datasets/upload'] });
  const jobs = useResource(() => can('training:read') ? training.list() : Promise.resolve(null), [can('training:read')], { watch: ['/training-jobs'] });
  const versions = useResource(() => can('models:read') ? models.list() : Promise.resolve(null), [can('models:read')], { watch: ['/model-versions', '/models/', '/training-jobs'] });
  const deployment = useResource(() => can('deployments:read') ? serving.deployment() : Promise.resolve(null), [can('deployments:read')], { watch: ['/model-versions', '/models/'] });
  const usage = useResource(() => can('usage:read') ? billing.usage() : Promise.resolve(null), [can('usage:read')], { watch: ['/training-jobs', '/products', '/events', '/datasets', '/model-versions', '/models/'] });
  const active = versions.data?.items?.find(version => version.status === 'active');
  const latest = jobs.data?.items?.slice().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  const accepted = usage.data?.dimensions?.find(d => d.type === 'accepted_events');
  const warnings = usage.data?.dimensions?.filter(d => ['exhausted', 'approaching'].includes(quotaState(d.used, d.limit).status)) ?? [];
  const next = catalog.data?.total === 0 && can('catalog:write') ? { to: '/products/sync', label: 'Add your catalog', body: 'Start with the products you want to recommend.' }
    : accepted?.used === 0 && can('events:write') ? { to: '/events/submit', label: 'Send interaction events', body: 'Record how customers interact with your products.' }
    : jobs.data?.items?.length === 0 && can('training:write') ? { to: '/training', label: 'Prepare a model', body: 'Review training options and the available data.' }
    : versions.data?.items?.length && !active && can('models:deploy') ? { to: '/models', label: 'Review a model for activation', body: 'Choose a version after reviewing its source and quality.' }
    : active && can('deployments:read') ? { to: '/service-status', label: 'Monitor recommendation traffic', body: 'Check request volume, errors and fallback usage.' }
    : { to: '/integration', label: 'Connect your application', body: 'Use the integration reference to send data and request recommendations.' };
  return <Page title="Overview" subtitle="Your data, model and recommendation service." actions={[{ label: 'Refresh', onClick: () => { void catalog.reload(); void jobs.reload(); void versions.reload(); void deployment.reload(); void usage.reload(); } }]}>
    {warnings.length ? <Banner tone={warnings.some(d => quotaState(d.used, d.limit).status === 'exhausted') ? 'warn' : 'info'} title="Usage needs attention">{warnings.map(d => `${humanize(d.type)}: ${quotaState(d.used, d.limit).label.toLowerCase()}`).join(' · ')}. <Link to="/usage">Review usage and limits</Link></Banner> : null}
    {can('models:read') || can('deployments:read') ? <Panel title="Recommendation service">
      {versions.error ? <ErrorBanner error={versions.error} title="Model state unavailable" onRetry={versions.reload} /> : null}
      {deployment.error ? <ErrorBanner error={deployment.error} title="Serving state unavailable" onRetry={deployment.reload} /> : null}
      {(versions.loading && !versions.data) || (deployment.loading && !deployment.data) ? <Skeleton rows={2} /> : <dl className="overview-list">
        {can('models:read') && versions.data ? <div><dt>Active model</dt><dd>{active ? <Link className="mono" to={`/models/${active.id}`}>{active.version_tag}</Link> : 'No active model'}</dd></div> : null}
        {deployment.data ? <div><dt>Serving configuration</dt><dd><Badge group="deploy" value={deployment.data.status} /> <span className="muted">{deployment.data.last_transition_at ? `Activated ${fmtDateTime(deployment.data.last_transition_at)}` : 'No model activated'}</span></dd></div> : null}
      </dl>}
      <p className="footnote">Activation selects a model. Request metrics on Service Status show how serving is performing.</p>
    </Panel> : null}
    <Panel title="Data and training">
      {catalog.error ? <ErrorBanner error={catalog.error} title="Catalog unavailable" onRetry={catalog.reload} /> : null}
      {jobs.error ? <ErrorBanner error={jobs.error} title="Training history unavailable" onRetry={jobs.reload} /> : null}
      {usage.error ? <ErrorBanner error={usage.error} title="Usage unavailable" onRetry={usage.reload} /> : null}
      <dl className="overview-list">
        {can('catalog:read') ? <div><dt>Catalog</dt><dd>{catalog.data ? <Link to="/products">{fmtNumber(catalog.data.total)} products</Link> : catalog.loading ? 'Loading…' : 'Unavailable'}</dd></div> : null}
        {can('usage:read') ? <div><dt>Accepted interactions</dt><dd>{accepted ? `${fmtNumber(accepted.used)} this usage period` : usage.loading ? 'Loading…' : 'Unavailable'}</dd></div> : null}
        {can('training:read') ? <div><dt>Latest training</dt><dd>{latest ? <><Link className="mono" to={`/training/${latest.id}`}>{fmtDateTime(latest.created_at)}</Link><Badge group="job" value={latest.status} /></> : jobs.data ? 'No training jobs yet' : jobs.loading ? 'Loading…' : 'Unavailable'}</dd></div> : null}
      </dl>
    </Panel>
    <section className="next-step"><div><h2>{next.label}</h2><p>{next.body}</p></div><Link className="btn btn-primary" to={next.to}>Continue</Link></section>
  </Page>;
}
