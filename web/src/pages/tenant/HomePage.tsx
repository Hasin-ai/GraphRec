import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { billing, datasets, events, models, products, recommendations, serving, training } from "../../api";
import type { RecommendationResult } from "../../api/types";
import { describeError } from "../../api/client";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDate, fmtNumber } from "../../lib/format";
import { daysAgoLabel, daysSince, modelLabel, modelTypeLabel } from "../../lib/labels";
import { quotaMessage, quotaState } from "../../lib/quota";
import { Dialog } from "../../ui/Dialog";
import { Field, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { ErrorBanner, IdChip, Skeleton } from "../../ui/primitives";
import { Alert, ButtonLink, HelpTip, RelativeTime, SectionHeader, StatusDot, StatusPill, type StatusTone } from "../../ui/kit";

/**
 * Overview answers, in order: is the recommendation system healthy, how is it
 * performing, and what should I do next. Problems are listed compactly inside
 * the health summary rather than leading the page (critique round 5).
 */
type Health = "ok" | "warn" | "danger" | "info" | "neu";
type Severity = "blocking" | "warning";
interface Issue { id: string; severity: Severity; title: string; body: string; fix?: { label: string; to: string } }

const HEALTH_WORD: Record<Health, string> = { ok: "Healthy", warn: "Needs attention", danger: "Blocked", info: "Ready", neu: "Not set up" };
const HEALTH_TONE: Record<Health, StatusTone> = { ok: "success", warn: "warning", danger: "danger", info: "info", neu: "neutral" };
const HEALTH_STATE: Record<Health, string> = { ok: "OK", warn: "Attention", danger: "Problem", info: "Info", neu: "Unknown" };

function HealthRow({ label, state, word, detail, to }: { label: string; state: Health; word?: string; detail: ReactNode; to: string }) {
  return <Link to={to} className={`hl-row hl-${state}`}>
    <span className="hl-label">{label}</span>
    <span className="hl-word"><StatusDot tone={HEALTH_TONE[state]}>{word ?? HEALTH_WORD[state]}</StatusDot><span className="sr-only"> ({HEALTH_STATE[state]})</span></span>
    <span className="hl-detail">{detail}</span>
  </Link>;
}

function Metric({ label, value, note, help, empty }: { label: string; value: ReactNode; note?: ReactNode; help?: string; empty?: string }) {
  return <div className="metric-tile">
    <div className="mt-label">{label}{help ? <HelpTip label={label}>{help}</HelpTip> : null}</div>
    <div className={`mt-value${value === "—" ? " is-empty" : ""}`}>{value === "—" ? (empty ?? "No data yet") : value}</div>
    {note ? <div className="mt-note">{note}</div> : null}
  </div>;
}

type Step = { label: string; state: "done" | "warn" | "todo" | "locked"; detail: string; to: string };

// A role without the scope behind a stage cannot see its state; say so instead of "not started".
const LOCKED_DETAIL = "Not visible to your role";

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
  // Roles without usage:read (developers) still need to know whether events arrive.
  const latestEvents = useResource(() => can('events:read') && !can('usage:read') ? events.list({ limit: 1 }).catch(() => null) : Promise.resolve(null), [can('events:read'), can('usage:read')], { watch: ['/events'] });
  const [trying, setTrying] = useState(false);

  const all = [catalog, jobs, versions, deployment, metrics, usage, snapshots, batches];
  const loading = all.some(r => r.loading);
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
  const latestBatch = (Array.isArray(batches.data) ? batches.data : []).slice().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  const latestEvent = latestEvents.data?.[0];
  const dims = usage.data?.dimensions ?? [];
  const accepted = dims.find(x => x.type === 'accepted_events');
  const stored = dims.find(x => x.type === 'stored_products');
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
  if (noEvents) issues.push({ id: 'events', severity: 'warning', title: 'No interaction events this billing period',
    body: `The serving model was trained ${daysAgoLabel(active?.created_at)} and has received no new behaviour data, so recommendations don't reflect recent activity.`,
    fix: can('events:write') ? { label: 'Send events', to: '/events/submit' } : { label: 'Integration guide', to: '/integration' } });
  if (m?.error_rate && m.error_rate > 0.05) issues.push({ id: 'errors', severity: 'warning', title: `Error rate is ${(m.error_rate * 100).toFixed(1)}%`, body: 'More than 5% of recommendation requests failed in the last 24 hours.', fix: { label: 'Investigate', to: '/service-status' } });
  issues.sort((a, b) => (a.severity === 'blocking' ? 0 : 1) - (b.severity === 'blocking' ? 0 : 1));
  const blocking = issues.filter(i => i.severity === 'blocking').length;
  const warnings = issues.length - blocking;
  const issueSummary = [blocking ? `${blocking} blocking ${blocking === 1 ? 'issue' : 'issues'}` : null, warnings ? `${warnings} ${warnings === 1 ? 'warning' : 'warnings'}` : null].filter(Boolean).join(' · ');

  // ── health rows ─────────────────────────────────────────────────────────
  const servingHealth: Health = !d ? 'neu' : !servingUp ? 'danger' : requests === 0 ? 'info' : 'ok';
  const modelHealth: Health = !versions.data ? 'neu' : !active ? 'danger' : 'ok';
  const eventHealth: Health = !accepted ? 'neu' : noEvents ? 'warn' : 'ok';
  const catalogHealth: Health = productCount === undefined ? 'neu' : productCount === 0 ? 'danger' : overBy > 0 ? 'danger' : 'ok';

  // ── pipeline: Catalog → Events → Dataset → Training → Model → Serving ───
  const rawSteps: Array<Step & { scope: boolean }> = [
    { scope: can('catalog:read'), label: 'Catalog', state: !productCount ? 'todo' : overBy > 0 ? 'warn' : 'done', detail: productCount ? `${fmtNumber(productCount)} products` : 'No products', to: '/products' },
    { scope: can('usage:read') || can('events:read'), label: 'Events', state: noEvents ? 'warn' : (accepted?.used || (!accepted && (latestEvent || latestBatch))) ? 'done' : 'todo', detail: accepted?.used ? `${fmtNumber(accepted.used)} this period` : latestEvent ? `Last event ${fmtDate(latestEvent.created_at)}` : latestBatch ? `Last batch ${fmtDate(latestBatch.created_at)}` : 'None received', to: '/events/submit' },
    { scope: can('training:read'), label: 'Dataset', state: latestSnapshot ? 'done' : 'todo', detail: latestSnapshot ? `Snapshot ${fmtDate(latestSnapshot.created_at)}` : 'No snapshot', to: '/datasets' },
    { scope: can('training:read'), label: 'Training', state: latestJob?.status === 'succeeded' ? 'done' : latestJob?.status === 'failed' ? 'warn' : latestJob ? 'warn' : 'todo', detail: latestJob ? `Last run ${fmtDate(latestJob.created_at)}` : 'No runs', to: '/training' },
    { scope: can('models:read'), label: 'Model', state: active ? 'done' : allVersions.length ? 'warn' : 'todo', detail: active ? `v${activeN} active` : allVersions.length ? 'None active' : 'No versions', to: '/models' },
    { scope: can('deployments:read'), label: 'Serving', state: servingUp ? (requests ? 'done' : 'warn') : 'todo', detail: servingUp ? (requests ? `${fmtNumber(requests)} req · 24 h` : 'No traffic') : 'Not serving', to: '/service-status' },
  ];
  const steps: Step[] = rawSteps.map(({ scope, ...step }) => scope ? step : { ...step, state: 'locked', detail: LOCKED_DETAIL });

  // The getting-started checklist counts exactly the steps it shows.
  const checklist: { title: string; detail: string; done: boolean; action: ReactNode }[] = [
    { title: 'Add your catalog', detail: 'Products the recommender can choose from.', done: !!productCount,
      action: can('catalog:write') ? <Link className="btn btn-primary btn-sm" to="/products/sync">Import catalog</Link> : null },
    { title: 'Send interaction events', detail: 'Views, carts and purchases the model learns from.', done: !!accepted?.used,
      action: can('events:write') ? <Link className="btn btn-secondary btn-sm" to="/events/submit">Send events</Link> : null },
    { title: 'Train a model', detail: 'Creates a model version from your data.', done: allVersions.length > 0,
      action: can('training:read') ? <Link className="btn btn-secondary btn-sm" to="/training">Train a model</Link> : null },
    { title: 'Activate it and request recommendations', detail: 'Start serving your storefront.', done: !!servingUp,
      action: can('models:read') ? <Link className="btn btn-secondary btn-sm" to="/models">Model versions</Link> : null },
  ];

  const pct = (v: number | null | undefined) => v === null || v === undefined ? '—' : `${(v * 100).toFixed(v < 0.01 && v > 0 ? 2 : 1)}%`;
  const canTry = servingUp && can('recommendations:read');

  return <Page title="Overview" subtitle="Health and performance of your recommendation system."
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
      <div className="ov-section-head"><h2 id="start-title">Get your recommendation system running</h2><span className="muted small">{checklist.filter(item => item.done).length} of {checklist.length} steps done</span></div>
      <ol className="checklist">
        {checklist.map(item => <li key={item.title} className={item.done ? 'done' : ''}><div><strong>{item.title}</strong><span>{item.detail}</span></div>{item.action}</li>)}
      </ol>
    </section> : null}

    {/* 2 — performance: what the API actually measures */}
    {isNew || !can('deployments:read') ? null : <section className="ov-section" aria-labelledby="perf-title">
      <SectionHeader id="perf-title" title="Performance" description="Live traffic over the last 24 hours. Model quality comes from offline evaluation." />
      <div className="metric-row">
        <Metric label="Requests (24 h)" value={m ? fmtNumber(requests) : '—'} empty="Not available" note={m ? (requests ? `${(m.request_rate ?? 0).toFixed(2)} per minute` : 'No traffic yet') : undefined} />
        <Metric label="p95 latency" value={m?.p95_latency_ms != null ? `${Math.round(m.p95_latency_ms)} ms` : '—'} empty="No traffic yet" help="95th-percentile response time of successful recommendation requests." note={requests ? 'Successful requests' : undefined} />
        <Metric label="Error rate" value={pct(m?.error_rate)} empty="No traffic yet" help="Share of recommendation requests that failed." note={requests ? `Fallback ${pct(m?.fallback_rate)}` : undefined} />
        <Metric label="NDCG@10" value={score('NDCG@10') !== null ? score('NDCG@10')!.toFixed(3) : '—'} empty="Not evaluated"
          help="Normalized Discounted Cumulative Gain at 10: how high the true next item ranks in the top 10, weighted by position (0–1, higher is better). Offline validation of the serving model."
          note={score('Hit@10') !== null ? <span className="tt">Hit@10 {score('Hit@10')!.toFixed(3)}<HelpTip label="Hit@10">Share of test users whose true next item appears anywhere in the top 10.</HelpTip></span> : undefined} />
      </div>
      <Alert compact tone="info">Click-through and conversion aren't measured yet. They need impression and click feedback linked to recommendation requests.</Alert>
    </section>}

    {/* 1 — compact system health; issues are a short list inside it */}
    {isNew || anyError ? null : (deployment.loading && !d) || (usage.loading && !usage.data) ? <Skeleton rows={2} /> :
      <section className="health-card" aria-labelledby="health-title">
        <div className="hc-head"><h2 id="health-title">System health</h2>
          <StatusPill tone={blocking ? 'danger' : warnings ? 'warning' : 'success'} icon={blocking ? 'alert-octagon' : warnings ? 'alert-triangle' : 'check-circle'}>{issues.length ? issueSummary : 'All systems healthy'}</StatusPill></div>
        <div className="hl-grid">
          {can('deployments:read') ? <HealthRow label="Serving" state={servingHealth} word={servingHealth === 'info' ? 'Ready · no traffic' : undefined} to="/service-status"
            detail={!d ? '—' : servingUp ? (requests ? `${fmtNumber(requests)} requests in 24 h` : 'No requests in 24 h') : 'No model active'} /> : null}
          {can('models:read') ? <HealthRow label="Model" state={modelHealth} word={active ? 'Active' : undefined} to={active ? `/models/${active.id}` : '/models'}
            detail={active ? <>{modelTypeLabel(active.model_type)} v{activeN} · trained <RelativeTime value={active.created_at} /></> : 'No version active'} /> : null}
          {can('usage:read') ? <HealthRow label="Event pipeline" state={eventHealth} word={noEvents ? 'No events' : undefined} to="/events/submit"
            detail={accepted ? (noEvents ? <>None this period{latestBatch ? <> · last batch <RelativeTime value={latestBatch.created_at} /></> : null}</> : `${fmtNumber(accepted.used)} accepted this period`) : '—'} /> : null}
          {can('catalog:read') ? <HealthRow label="Catalog" state={catalogHealth} word={overBy > 0 ? 'Over quota' : undefined} to="/products"
            detail={productCount === undefined ? '—' : stored?.limit != null ? `${fmtNumber(productCount)} of ${fmtNumber(stored.limit)} products` : `${fmtNumber(productCount)} products`} /> : null}
        </div>
        {issues.length ? <ul className="issue-list" aria-label="Issues">{issues.map(issue => <li key={issue.id}>
          <Alert compact tone={issue.severity === 'blocking' ? 'danger' : 'warning'} title={<><span className="sr-only">{issue.severity === 'blocking' ? 'Blocking: ' : 'Warning: '}</span>{issue.title}</>}
            action={issue.fix ? <ButtonLink size="sm" to={issue.fix.to}>{issue.fix.label}</ButtonLink> : undefined}>{issue.body}</Alert>
        </li>)}</ul> : null}
      </section>}

    {/* 3 — traffic + active model side by side */}
    {isNew ? null : <div className="split">
      {can('deployments:read') ? <section className="panel-card" aria-labelledby="traffic-title">
        <div className="pc-head"><h2 id="traffic-title">Recommendation traffic</h2><span className="muted small">Last 24 h</span></div>
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
        <div className="pc-head"><h2 id="model-title">Serving model</h2>{active ? <StatusPill tone="success">Serving</StatusPill> : null}</div>
        {active ? <>
          <div className="pm-name">{modelTypeLabel(active.model_type)} <span>v{activeN}</span><span className="muted small"> of {allVersions.length}</span></div>
          <dl className="pm-stats">
            <div><dt>NDCG@10</dt><dd>{score('NDCG@10')?.toFixed(3) ?? '—'}</dd></div>
            <div><dt>Hit@10</dt><dd>{score('Hit@10')?.toFixed(3) ?? '—'}</dd></div>
            <div><dt>Trained</dt><dd><RelativeTime value={active.created_at} /></dd></div>
          </dl>
          {rolledBackFrom ? <p className="pm-note">Rolled back from {modelLabel(rolledBackFrom, allVersions).split(' · ')[1]} <RelativeTime value={active.activated_at ?? rolledBackFrom.activated_at} />.</p> : null}
          {modelAge > 14 && noEvents ? <p className="pm-note warn">Trained on data that is {modelAge} days old.</p> : null}
          <div className="row small muted">Version <IdChip value={active.version_tag} length={24} label="Version ID" /></div>
        </> : <p className="muted">No version is active. {allVersions.length ? 'Activate one on Model Versions.' : 'Train a model to create the first version.'}</p>}
        <div className="pc-foot"><Link to={active ? `/models/${active.id}` : '/models'}>{active ? 'View model' : 'Model versions'} →</Link></div>
      </section> : null}
    </div>}

    {/* 4 — the pipeline the product is built around */}
    {isNew ? null : <section className="ov-section" aria-labelledby="pipe-title">
      <SectionHeader id="pipe-title" title="Data and model pipeline" />
      <ol className="pipeline">{steps.map(step => <li key={step.label} className={`pl-${step.state}`}>
        <Link to={step.to}><span className="pl-icon" aria-hidden="true">{step.state === 'done' ? '✓' : step.state === 'warn' ? '!' : step.state === 'locked' ? '–' : '○'}</span>
          <span className="pl-label">{step.label}</span><span className="pl-detail">{step.detail}</span>
          <span className="sr-only">{step.state === 'done' ? 'complete' : step.state === 'warn' ? 'needs attention' : step.state === 'locked' ? 'not visible to your role' : 'not started'}</span></Link>
      </li>)}</ol>
    </section>}

    {trying ? <TryRecommendation onClose={() => setTrying(false)} /> : null}
  </Page>;
}
