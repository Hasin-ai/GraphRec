import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { billing, datasets, events, models, products, recommendations, serving, training } from "../../api";
import type { RecommendationResult } from "../../api/types";
import { describeError } from "../../api/client";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDate, fmtDateTime, fmtDateTimeFull, fmtNumber } from "../../lib/format";
import { daysAgoLabel, daysSince, modelLabel, modelTypeLabel } from "../../lib/labels";
import { quotaMessage, quotaState } from "../../lib/quota";
import { Dialog } from "../../ui/Dialog";
import { Field, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { ErrorBanner, IdChip, Skeleton } from "../../ui/primitives";

/**
 * Overview answers, in order: is the recommendation system healthy, how is it
 * performing, and what should I do next. Problems are listed compactly inside
 * the health summary rather than leading the page (critique round 5).
 */
type Health = "ok" | "warn" | "danger" | "neu";
type Severity = "blocking" | "warning";
interface Issue { id: string; severity: Severity; title: string; body: string; fix?: { label: string; to: string } }

const HEALTH_WORD: Record<Health, string> = { ok: "Healthy", warn: "Needs attention", danger: "Blocked", neu: "Not set up" };

function HealthRow({ label, state, word, detail, to }: { label: string; state: Health; word?: string; detail: ReactNode; to: string }) {
  return <Link to={to} className={`hl-row hl-${state}`}>
    <span className="hl-dot" aria-hidden="true" />
    <span className="hl-label">{label}</span>
    <span className="hl-word">{word ?? HEALTH_WORD[state]}</span>
    <span className="hl-detail">{detail}</span>
  </Link>;
}

function Metric({ label, value, note, help }: { label: string; value: ReactNode; note?: ReactNode; help?: string }) {
  return <div className="metric-tile" title={help}>
    <div className="mt-label">{label}</div>
    <div className={`mt-value${value === "—" ? " is-empty" : ""}`}>{value}</div>
    {note ? <div className="mt-note">{note}</div> : null}
  </div>;
}

type Step = { label: string; state: "done" | "warn" | "todo"; detail: string; to: string };

function TryRecommendation({ onClose }: { onClose: () => void }) {
  const [userId, setUserId] = useState("");
  const [topN, setTopN] = useState("10");
  const [result, setResult] = useState<RecommendationResult | null>(null);
  return <Dialog title="Try a recommendation" width={560} confirmLabel={result ? "Run again" : "Get recommendations"}
    body="Sends one real request to your recommendation service. It counts toward this period's recommendation-request quota."
    onClose={onClose}
    onConfirm={async () => {
      const n = Number(topN);
      if (!Number.isInteger(n) || n < 1 || n > 100) return "Enter how many items to return, from 1 to 100.";
      try {
        setResult(await recommendations.get({ ...(userId.trim() ? { user_id: userId.trim() } : {}), top_n: n, context: { surface: "console_test" } }));
      } catch (error) { return describeError(error); }
    }}>
    <Field id="try-user" label="Customer ID (optional)" hint="Leave empty to see what an anonymous visitor gets.">
      <TextInput id="try-user" value={userId} onChange={setUserId} placeholder="e.g. 10423" />
    </Field>
    <Field id="try-n" label="Number of items">
      <TextInput id="try-n" type="number" min={1} max={100} value={topN} onChange={setTopN} />
    </Field>
    {result ? <div className="try-result" role="status">
      <div className="row small"><strong>{result.items.length} items</strong>
        <span className="muted">· {result.fallback_used ? `fallback (${result.fallback_tier.replace(/_/g, " ")})` : `model ${result.strategy.replace(/_/g, " ")}`}{result.applied_rules.length ? ` · rules: ${result.applied_rules.join(", ")}` : ""}</span></div>
      <ol>{result.items.map(item => <li key={item.position}><Link to={`/products/${encodeURIComponent(item.external_product_id)}`}>Product {item.external_product_id}</Link></li>)}</ol>
    </div> : null}
  </Dialog>;
}

export function HomePage() {
  const { can } = useSession();
  const catalog = useResource(() => can('catalog:read') ? products.list({ limit: 1 }) : Promise.resolve(null), [can('catalog:read')], { watch: ['/products', '/datasets/upload'] });
  const jobs = useResource(() => can('training:read') ? training.list() : Promise.resolve(null), [can('training:read')], { watch: ['/training-jobs'] });
  const versions = useResource(() => can('models:read') ? models.list() : Promise.resolve(null), [can('models:read')], { watch: ['/model-versions', '/models/', '/training-jobs'] });
  const deployment = useResource(() => can('deployments:read') ? serving.deployment() : Promise.resolve(null), [can('deployments:read')], { watch: ['/model-versions', '/models/'] });
  const metrics = useResource(() => can('deployments:read') ? serving.metrics(60 * 24).catch(() => null) : Promise.resolve(null), [can('deployments:read')]);
  const usage = useResource(() => can('usage:read') ? billing.usage() : Promise.resolve(null), [can('usage:read')], { watch: ['/training-jobs', '/products', '/events', '/datasets', '/model-versions', '/models/'] });
  const snapshots = useResource(() => can('training:read') ? datasets.listSnapshots().catch(() => null) : Promise.resolve(null), [can('training:read')]);
  const batches = useResource(() => can('events:read') ? events.listBatches().catch(() => null) : Promise.resolve(null), [can('events:read')]);
  const [trying, setTrying] = useState(false);

  const all = [catalog, jobs, versions, deployment, metrics, usage, snapshots, batches];
  const loading = all.some(r => r.loading);
  const [refreshedAt, setRefreshedAt] = useState<number | null>(null);
  useEffect(() => { if (!loading) setRefreshedAt(Date.now()); }, [loading]);
  const reloadAll = () => { all.forEach(r => void r.reload()); };

  // ── facts ───────────────────────────────────────────────────────────────
  const allVersions = versions.data?.items ?? [];
  const ordered = allVersions.slice().sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  const active = allVersions.find(v => v.status === 'active');
  const activeN = active ? ordered.findIndex(v => v.id === active.id) + 1 : 0;
  const rolledBackFrom = active ? allVersions.filter(v => v.id !== active.id && v.activated_at && Date.parse(v.created_at) > Date.parse(active.created_at)).sort((a, b) => Date.parse(b.activated_at!) - Date.parse(a.activated_at!))[0] : undefined;
  const validation = (active?.metrics as { validation?: Record<string, unknown> } | undefined)?.validation ?? {};
  const score = (k: string) => typeof validation[k] === 'number' ? (validation[k] as number) : null;
  const latestJob = jobs.data?.items?.slice().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  const latestSnapshot = snapshots.data?.items?.slice().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  const latestBatch = (batches.data ?? []).slice().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  const dims = usage.data?.dimensions ?? [];
  const accepted = dims.find(x => x.type === 'accepted_events');
  const stored = dims.find(x => x.type === 'stored_products');
  const periodStart = usage.data?.period_start;
  const d = deployment.data;
  const m = metrics.data;
  const servingUp = d?.status === 'available' && !!d.active_model_version_id;
  const requests = m?.request_count ?? 0;
  const noEvents = accepted?.used === 0;
  const productCount = catalog.data?.total;
  const overBy = stored && stored.limit !== null && stored.used > stored.limit ? stored.used - stored.limit : 0;
  const isNew = productCount === 0 && !!versions.data && allVersions.length === 0;
  const anyError = [catalog, jobs, versions, deployment, usage].some(r => r.error);
  const modelAge = active ? daysSince(active.created_at) ?? 0 : 0;

  // ── issues: counted by severity, worded by consequence ────────────────────
  const issues: Issue[] = [];
  if (d && !servingUp) issues.push({ id: 'serving', severity: 'blocking', title: 'Recommendations are not being served', body: d.failure_reason ?? 'No model version is active. Activate one to start answering requests.', fix: can('models:read') ? { label: 'Activate a model', to: '/models' } : undefined });
  if (overBy > 0 && stored) issues.push({ id: 'catalog', severity: 'blocking', title: 'New product additions are blocked',
    body: `Your catalog exceeds the plan limit by ${fmtNumber(overBy)} products (${fmtNumber(stored.used)} of ${fmtNumber(stored.limit)}). Existing products and recommendations keep working.`,
    fix: can('catalog:read') ? { label: 'Manage catalog', to: '/products' } : undefined });
  for (const dim of dims) {
    if (dim.type === 'stored_products') continue;
    const q = quotaState(dim.used, dim.limit);
    if (q.status !== 'exhausted' && q.status !== 'approaching') continue;
    const msg = quotaMessage(dim.type, dim.used, dim.limit);
    issues.push({ id: dim.type, severity: q.status === 'exhausted' ? 'blocking' : 'warning', title: msg.title, body: msg.body, fix: { label: 'Review limits', to: '/usage' } });
  }
  if (noEvents) issues.push({ id: 'events', severity: 'warning', title: `No interaction events since ${periodStart ? fmtDate(periodStart) : 'the period started'}`,
    body: `The serving model was trained ${daysAgoLabel(active?.created_at)} and has received no new behaviour data, so recommendations don't reflect recent activity.`,
    fix: can('events:write') ? { label: 'Send events', to: '/events/submit' } : { label: 'Integration guide', to: '/integration' } });
  if (m?.error_rate && m.error_rate > 0.05) issues.push({ id: 'errors', severity: 'warning', title: `Error rate is ${(m.error_rate * 100).toFixed(1)}%`, body: 'More than 5% of recommendation requests failed in the last 24 hours.', fix: { label: 'Investigate', to: '/service-status' } });
  issues.sort((a, b) => (a.severity === 'blocking' ? 0 : 1) - (b.severity === 'blocking' ? 0 : 1));
  const blocking = issues.filter(i => i.severity === 'blocking').length;
  const warnings = issues.length - blocking;
  const issueSummary = [blocking ? `${blocking} blocking ${blocking === 1 ? 'issue' : 'issues'}` : null, warnings ? `${warnings} ${warnings === 1 ? 'warning' : 'warnings'}` : null].filter(Boolean).join(' · ');

  // ── health rows ─────────────────────────────────────────────────────────
  const servingHealth: Health = !d ? 'neu' : !servingUp ? 'danger' : requests === 0 ? 'warn' : 'ok';
  const modelHealth: Health = !versions.data ? 'neu' : !active ? 'danger' : 'ok';
  const eventHealth: Health = !accepted ? 'neu' : noEvents ? 'warn' : 'ok';
  const catalogHealth: Health = productCount === undefined ? 'neu' : productCount === 0 ? 'danger' : overBy > 0 ? 'danger' : 'ok';

  // ── pipeline: Catalog → Events → Dataset → Training → Model → Serving ───
  const steps: Step[] = [
    { label: 'Catalog', state: !productCount ? 'todo' : overBy > 0 ? 'warn' : 'done', detail: productCount ? `${fmtNumber(productCount)} products` : 'No products', to: '/products' },
    { label: 'Events', state: noEvents ? 'warn' : accepted?.used ? 'done' : 'todo', detail: accepted?.used ? `${fmtNumber(accepted.used)} this period` : latestBatch ? `Last batch ${fmtDate(latestBatch.created_at)}` : 'None received', to: '/events/submit' },
    { label: 'Dataset', state: latestSnapshot ? 'done' : 'todo', detail: latestSnapshot ? `Snapshot ${fmtDate(latestSnapshot.created_at)}` : 'No snapshot', to: '/datasets' },
    { label: 'Training', state: latestJob?.status === 'succeeded' ? 'done' : latestJob?.status === 'failed' ? 'warn' : latestJob ? 'warn' : 'todo', detail: latestJob ? `Last run ${fmtDate(latestJob.created_at)}` : 'No runs', to: '/training' },
    { label: 'Model', state: active ? 'done' : allVersions.length ? 'warn' : 'todo', detail: active ? `v${activeN} active` : allVersions.length ? 'None active' : 'No versions', to: '/models' },
    { label: 'Serving', state: servingUp ? (requests ? 'done' : 'warn') : 'todo', detail: servingUp ? (requests ? `${fmtNumber(requests)} req · 24 h` : 'No traffic') : 'Not serving', to: '/service-status' },
  ];

  const pct = (v: number | null | undefined) => v === null || v === undefined ? '—' : `${(v * 100).toFixed(v < 0.01 && v > 0 ? 2 : 1)}%`;
  const canTry = servingUp && can('recommendations:read');

  return <Page title="Overview" subtitle="Health and performance of your recommendation system."
    updated={refreshedAt ? <span title={fmtDateTimeFull(refreshedAt)}>{loading ? 'Refreshing…' : `Last refreshed ${new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).format(refreshedAt)}`}</span> : null}
    actions={[
      ...(canTry ? [{ label: 'Try a recommendation', variant: 'primary' as const, onClick: () => setTrying(true) }] : []),
      { label: 'Refresh', icon: 'refresh' as const, disabled: loading, onClick: reloadAll },
    ]}>

    {(() => {
      const failed = [versions, deployment, catalog, jobs, usage, metrics].filter(x => x.error);
      if (!failed.length) return null;
      return <ErrorBanner error={failed[0].error} title={failed.length > 1 ? `GraphRec couldn't load the overview (${failed.length} of 6 data sources failed)` : "Part of the overview couldn't be loaded"} onRetry={reloadAll} />;
    })()}

    {isNew ? <section aria-labelledby="start-title" className="ov-section">
      <div className="ov-section-head"><h2 id="start-title">Get your recommendation system running</h2><span className="muted small">{steps.filter(s => s.state === 'done').length} of {steps.length} steps done</span></div>
      <ol className="checklist">
        <li className={productCount ? 'done' : ''}><div><strong>Add your catalog</strong><span>Products the recommender can choose from.</span></div>{can('catalog:write') ? <Link className="btn btn-primary btn-sm" to="/products/sync">Import catalog</Link> : null}</li>
        <li className={accepted?.used ? 'done' : ''}><div><strong>Send interaction events</strong><span>Views, carts and purchases the model learns from.</span></div>{can('events:write') ? <Link className="btn btn-secondary btn-sm" to="/events/submit">Send events</Link> : null}</li>
        <li className={allVersions.length ? 'done' : ''}><div><strong>Train a model</strong><span>Creates a model version from your data.</span></div>{can('training:read') ? <Link className="btn btn-secondary btn-sm" to="/training">Train a model</Link> : null}</li>
        <li className={servingUp ? 'done' : ''}><div><strong>Activate it and request recommendations</strong><span>Start serving your storefront.</span></div>{can('models:read') ? <Link className="btn btn-secondary btn-sm" to="/models">Model versions</Link> : null}</li>
      </ol>
    </section> : null}

    {/* 1 — compact system health; issues are a short list inside it */}
    {isNew || anyError ? null : (deployment.loading && !d) || (usage.loading && !usage.data) ? <Skeleton rows={2} /> :
      <section className="health-card" aria-labelledby="health-title">
        <div className="hc-head"><h2 id="health-title">System health</h2>
          <span className={`hc-sum ${blocking ? 'tone-danger' : warnings ? 'tone-warn' : 'tone-ok'}`}>{issues.length ? issueSummary : 'All systems healthy'}</span></div>
        <div className="hl-grid">
          {can('deployments:read') ? <HealthRow label="Serving" state={servingHealth} word={servingHealth === 'warn' ? 'Ready, no traffic' : undefined} to="/service-status"
            detail={!d ? '—' : servingUp ? (requests ? `${fmtNumber(requests)} requests in 24 h` : 'No requests in the last 24 hours') : 'No model active'} /> : null}
          {can('models:read') ? <HealthRow label="Model" state={modelHealth} word={active ? 'Active' : undefined} to={active ? `/models/${active.id}` : '/models'}
            detail={active ? `${modelTypeLabel(active.model_type)} v${activeN} · trained ${daysAgoLabel(active.created_at)}` : 'No version active'} /> : null}
          {can('usage:read') ? <HealthRow label="Event pipeline" state={eventHealth} word={noEvents ? 'No events' : undefined} to="/events/submit"
            detail={accepted ? (noEvents ? `None since ${periodStart ? fmtDate(periodStart) : 'period start'}${latestBatch ? ` · last batch ${fmtDate(latestBatch.created_at)}` : ''}` : `${fmtNumber(accepted.used)} accepted since ${periodStart ? fmtDate(periodStart) : 'period start'}`) : '—'} /> : null}
          {can('catalog:read') ? <HealthRow label="Catalog" state={catalogHealth} word={overBy > 0 ? 'Over quota' : undefined} to="/products"
            detail={productCount === undefined ? '—' : stored?.limit != null ? `${fmtNumber(productCount)} of ${fmtNumber(stored.limit)} products` : `${fmtNumber(productCount)} products`} /> : null}
        </div>
        {issues.length ? <ul className="issue-list">{issues.map(issue => <li key={issue.id} className={`sev-${issue.severity}`}>
          <span className="sev-pill">{issue.severity === 'blocking' ? 'Blocking' : 'Warning'}</span>
          <div className="il-text"><strong>{issue.title}</strong><span>{issue.body}</span></div>
          {issue.fix ? <Link className="btn btn-secondary btn-sm" to={issue.fix.to}>{issue.fix.label}</Link> : null}
        </li>)}</ul> : null}
      </section>}

    {/* 2 — performance: what the API actually measures */}
    {isNew ? null : <section className="ov-section" aria-labelledby="perf-title">
      <div className="ov-section-head"><h2 id="perf-title">Performance</h2><span className="muted small">Live traffic over the last 24 hours · model quality from offline evaluation</span></div>
      <div className="metric-row">
        <Metric label="Recommendation requests" value={m ? fmtNumber(requests) : '—'} note={m ? (requests ? `${(m.request_rate ?? 0).toFixed(2)} per minute` : 'No requests yet') : 'Not available'} />
        <Metric label="p95 latency" value={m?.p95_latency_ms != null ? `${Math.round(m.p95_latency_ms)} ms` : '—'} note={requests ? 'Successful requests' : 'Appears with traffic'} />
        <Metric label="Error rate" value={pct(m?.error_rate)} note={requests ? `Fallback ${pct(m?.fallback_rate)}` : 'Appears with traffic'} />
        <Metric label="Model quality" value={score('NDCG@10') !== null ? score('NDCG@10')!.toFixed(3) : '—'} help="Offline validation score of the serving model. Higher is better."
          note={score('Hit@10') !== null ? <>NDCG@10 · Hit@10 {score('Hit@10')!.toFixed(3)}</> : 'No offline evaluation'} />
      </div>
      <p className="footnote">Click-through and conversion aren't measured yet: they need impression and click feedback linked to recommendation requests.</p>
    </section>}

    {/* 3 — traffic + active model side by side */}
    {isNew ? null : <div className="split">
      {can('deployments:read') ? <section className="panel-card" aria-labelledby="traffic-title">
        <div className="pc-head"><h2 id="traffic-title">Recommendation traffic</h2><span className="muted small">Last 24 hours</span></div>
        {metrics.loading && !m ? <Skeleton rows={2} /> : requests === 0 ? <div className="empty-inline">
          <svg aria-hidden="true" viewBox="0 0 120 48" width="120" height="48"><path d="M2 44h116" stroke="currentColor" strokeWidth="1.5" opacity=".3" /><path d="M6 38l18-10 16 6 18-18 16 9 18-12 20 4" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="4 4" strokeLinecap="round" opacity=".45" /></svg>
          <strong>No recommendation requests in the last 24 hours</strong>
          <p>{servingUp ? 'The service is ready. Send a test request, or connect your storefront using the integration guide.' : 'Activate a model version to start serving.'}</p>
          <div className="row">{canTry ? <button type="button" className="btn btn-secondary btn-sm" onClick={() => setTrying(true)}>Try a recommendation</button> : null}<Link className="btn btn-secondary btn-sm" to="/integration">Integration guide</Link></div>
        </div> : <div className="kv-grid">
          <div><dt>Requests</dt><dd>{fmtNumber(requests)}</dd></div>
          <div><dt>p95 latency</dt><dd>{m?.p95_latency_ms != null ? `${Math.round(m.p95_latency_ms)} ms` : '—'}</dd></div>
          <div><dt>Error rate</dt><dd>{pct(m?.error_rate)}</dd></div>
          <div><dt>Fallback rate</dt><dd>{pct(m?.fallback_rate)}</dd></div>
        </div>}
        <div className="pc-foot"><Link to="/service-status">Service status →</Link></div>
      </section> : null}

      {can('models:read') ? <section className="panel-card" aria-labelledby="model-title">
        <div className="pc-head"><h2 id="model-title">Serving model</h2>{active ? <span className="tag badge badge-ok badge-dot no-cap"><span className="dot" aria-hidden="true" />Serving</span> : null}</div>
        {active ? <>
          <div className="pm-name">{modelTypeLabel(active.model_type)} <span>v{activeN}</span><span className="muted small"> of {allVersions.length}</span></div>
          <dl className="pm-stats">
            <div><dt>NDCG@10</dt><dd>{score('NDCG@10')?.toFixed(3) ?? '—'}</dd></div>
            <div><dt>Hit@10</dt><dd>{score('Hit@10')?.toFixed(3) ?? '—'}</dd></div>
            <div><dt>Trained</dt><dd title={fmtDateTimeFull(active.created_at)}>{daysAgoLabel(active.created_at)}</dd></div>
          </dl>
          {rolledBackFrom ? <p className="pm-note">↩ Rolled back from {modelLabel(rolledBackFrom, allVersions).split(' · ')[1]} on {fmtDateTime(active.activated_at ?? rolledBackFrom.activated_at)}. No reason was recorded.</p> : null}
          {modelAge > 14 && noEvents ? <p className="pm-note warn">Trained on data that is {modelAge} days old.</p> : null}
          <div className="row small muted">Version <IdChip value={active.version_tag} length={24} label="Version ID" /></div>
        </> : <p className="muted">No version is active. {allVersions.length ? 'Activate one on Model Versions.' : 'Train a model to create the first version.'}</p>}
        <div className="pc-foot"><Link to={active ? `/models/${active.id}` : '/models'}>{active ? 'View model' : 'Model versions'} →</Link></div>
      </section> : null}
    </div>}

    {/* 4 — the pipeline the product is built around */}
    {isNew ? null : <section className="ov-section" aria-labelledby="pipe-title">
      <div className="ov-section-head"><h2 id="pipe-title">Data and model pipeline</h2></div>
      <ol className="pipeline">{steps.map(step => <li key={step.label} className={`pl-${step.state}`}>
        <Link to={step.to}><span className="pl-icon" aria-hidden="true">{step.state === 'done' ? '✓' : step.state === 'warn' ? '!' : '○'}</span>
          <span className="pl-label">{step.label}</span><span className="pl-detail">{step.detail}</span>
          <span className="sr-only">{step.state === 'done' ? 'complete' : step.state === 'warn' ? 'needs attention' : 'not started'}</span></Link>
      </li>)}</ol>
    </section>}

    {trying ? <TryRecommendation onClose={() => setTrying(false)} /> : null}
  </Page>;
}
