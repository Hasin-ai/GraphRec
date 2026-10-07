import { Link } from "react-router-dom";
import { billing } from "../../api";
import { useQueryState } from "../../hooks/useQueryState";
import { useResource } from "../../hooks/useResource";
import { Select } from "../../ui/Form";
import { useSession } from "../../hooks/useSession";
import { fmtDate, fmtDateTime, fmtNumber, fmtQuantity, humanize } from "../../lib/format";
import { quotaMessage, quotaState } from "../../lib/quota";
import { Page } from "../../ui/Page";
import { Cell, DataTable, ErrorBanner, PanelTable, Skeleton } from "../../ui/primitives";
import { Alert, ButtonLink, Card, Progress, StatusPill } from "../../ui/kit";
import { Icon } from "../../ui/icons";
import { usageLabel } from "../../lib/labels";

function RelativeTimeUntil({ value }: { value: string }) {
  const days = Math.ceil((Date.parse(value) - Date.now()) / 86_400_000);
  return <span title={fmtDateTime(value)}>{days <= 0 ? 'today' : days === 1 ? 'in 1 day' : `in ${days} days`}</span>;
}
import { UsageTrends } from "./UsageTrends";

/** The current month and the 11 before it, as YYYY-MM (UTC billing periods). */
export function recentPeriods(now = new Date()): { value: string; label: string }[] {
  return Array.from({ length: 12 }, (_, back) => {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - back, 1));
    const value = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
    return { value, label: back === 0 ? "This period" : d.toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" }) };
  });
}

export function UsagePage() {
  const { can } = useSession();
  const periods = recentPeriods();
  const [period, setPeriod] = useQueryState("period", periods[0].value);
  const past = period !== periods[0].value;
  const usage = useResource(() => billing.usage(past ? period : undefined), [period]);
  const subscription = useResource(() => can('billing:read') ? billing.subscription() : Promise.resolve(null), [can('billing:read')]);
  const dims = usage.data?.dimensions ?? [];
  const exhausted = dims.filter(d => quotaState(d.used, d.limit).status === 'exhausted');
  const approaching = dims.filter(d => quotaState(d.used, d.limit).status === 'approaching');
  const plan = subscription.data;
  const rank = (d: (typeof dims)[number]) => { const st = quotaState(d.used, d.limit).status; return st === 'exhausted' ? 0 : st === 'approaching' ? 1 : d.limit === null ? 3 : 2; };
  const sortedDims = dims.slice().sort((a, b) => rank(a) - rank(b));
  const limited = dims.filter(d => d.limit !== null);
  const over = exhausted; const near = approaching;
  return <Page title="Usage & Quotas" subtitle={past ? "What this workspace used in a past billing period, against your current plan's limits." : "What this workspace has used this billing period, against your plan's limits."} actions={[{ label: 'Refresh', disabled: usage.loading, onClick: () => { void usage.reload(); void subscription.reload(); } }]}>
    <div className="field-inline"><label htmlFor="usage-period">Billing period</label><Select id="usage-period" value={period} onChange={setPeriod} options={periods} /></div>
    {past && usage.data ? <Alert tone="info" title={`Showing ${periods.find(p => p.value === period)?.label ?? period}`}>Counts such as events and recommendation requests are totals for that period. Stored products, retained versions, artifact storage and replicas are point-in-time and show their current value.</Alert> : null}
    {usage.error ? <ErrorBanner error={usage.error} onRetry={usage.reload} /> : null}
    {!usage.data && usage.loading ? <Skeleton /> : null}
    {usage.data ? <>
      <Card className="plan-card">
        <div className="plan-main">
          <div className="plan-title">{plan ? `${humanize(plan.plan_code)} plan` : 'Current plan'}{plan ? <StatusPill tone={plan.status === 'active' ? 'success' : 'neutral'}>{humanize(plan.status)}</StatusPill> : null}</div>
          <div className="plan-meta">
            {past ? <span><Icon name="clock" size={14} />{fmtDate(usage.data.period_start)} – {fmtDate(usage.data.period_end)}</span> : <span><Icon name="clock" size={14} />Resets {fmtDate(usage.data.reset_at)} (<RelativeTimeUntil value={usage.data.reset_at} />)</span>}
            <span>{over.length ? `${over.length} of ${limited.length} limits reached` : near.length ? `${near.length} of ${limited.length} limits near capacity` : `All ${limited.length} limits within capacity`}</span>
            <span><Link to="/pricing">Compare plans</Link></span>
          </div>
        </div>
        {over.length || near.length ? <span className="plan-cta muted small"><Icon name="info" size={14} />To raise a limit, ask your GraphRec platform operator to change your plan.</span> : null}
      </Card>
      {!past && (exhausted.length || approaching.length) ? <div className="alert-list">{[...exhausted, ...approaching].map(d => {
        const msg = quotaMessage(d.type, d.used, d.limit); const ex = quotaState(d.used, d.limit).status === 'exhausted';
        const fix = d.type === 'stored_products' && can('catalog:read') ? { label: 'Manage catalog', to: '/products' } : d.type === 'active_model_versions' && can('models:read') ? { label: 'Manage versions', to: '/models' } : null;
        return <Alert key={d.type} tone={ex ? 'danger' : 'warning'} title={msg.title} action={fix ? <ButtonLink size="sm" to={fix.to}>{fix.label}</ButtonLink> : undefined}>{msg.body}</Alert>; })}</div> : null}
      <DataTable minWidth={720} title="Limits this period" columns={['Usage type', { label: 'Used', align: 'right' }, { label: 'Limit', align: 'right' }, 'Usage', 'Status']}
        rows={sortedDims.map(d => { const q = quotaState(d.used, d.limit); const isOver = d.limit !== null && d.used > d.limit; const pct = d.limit ? Math.round((d.used / d.limit) * 100) : null;
          const tone = q.status === 'exhausted' ? 'danger' : q.status === 'approaching' ? 'warning' : 'neutral';
          return <tr key={d.type} className={q.status === 'exhausted' ? 'row-over' : q.status === 'approaching' ? 'row-near' : undefined}>
          <Cell sub={past && d.scope === 'current' ? 'Current value' : undefined}>{usageLabel(d.type)}</Cell><Cell mono align="right">{d.measured === false ? '—' : fmtQuantity(d.used, d.unit)}</Cell>
          <Cell mono align="right">{d.limit === null ? 'No limit' : fmtQuantity(d.limit, d.unit)}</Cell>
          <td>{d.measured === false ? <span className="td-muted">Not measured yet</span> : d.limit === null ? <span className="td-muted">Tracked, no limit</span> : <div className="usage-cell">
            <Progress value={d.used} max={d.limit} tone={tone} label={`${usageLabel(d.type)}: ${fmtQuantity(d.used, d.unit)} of ${fmtQuantity(d.limit, d.unit)}`} />
            <span className="u-text"><span>{fmtQuantity(d.used, d.unit)} of {fmtQuantity(d.limit, d.unit)}</span><span className="u-pct">{pct !== null ? `${pct}%` : 'Limit 0'}</span></span>
          </div>}</td>
          <td>{d.limit === null ? <span className="quiet-ok">No limit</span>
            : isOver ? <StatusPill tone="danger" icon="alert-octagon">Over limit</StatusPill>
            : q.status === 'exhausted' ? <StatusPill tone="danger" icon="alert-octagon">At limit</StatusPill>
            : q.status === 'approaching' ? <StatusPill tone="warning" icon="alert-triangle">Near limit</StatusPill>
            : <span className="quiet-ok"><Icon name="check" size={14} />OK</span>}</td>
        </tr>; })} count={`${dims.length} usage types · updated ${fmtDateTime(usage.data.last_reconciled_at)}`} empty={{ title: 'No usage measurements', body: 'Refresh to check for new measurements.' }} />
      <Alert compact tone="info">Period {fmtDate(usage.data.period_start)} – {fmtDate(usage.data.period_end)}. {usage.data.project_defaults ? 'Default limits apply.' : 'Your assigned plan and approved overrides apply.'} Product and model-version counts can lag a few minutes behind the catalog and model list.{plan && plan.period_end && Math.abs(Date.parse(plan.period_end) - Date.parse(usage.data.period_end)) > 86_400_000 ? <> Your subscription period ends {fmtDate(plan.period_end)}, but usage counters reset {fmtDate(usage.data.reset_at)}; limits follow the usage reset.</> : null}</Alert>
    </> : null}
    <UsageTrends />
    {subscription.error ? <ErrorBanner error={subscription.error} title="Subscription unavailable" onRetry={subscription.reload} /> : null}
    {plan ? <details className="details-section"><summary>Subscription · {humanize(plan.plan_code)} · {humanize(plan.status)}</summary>
      <p className="footnote">Plan defaults below. The usage table above includes effective overrides.</p>
      <PanelTable columns={['Plan limit', { label: 'Value', align: 'right' }]} rows={Object.entries(plan.limits).map(([key, value]) => <tr key={key}><Cell>{humanize(key)}</Cell><Cell mono align="right">{fmtNumber(value)}</Cell></tr>)} />
    </details> : null}
  </Page>;
}
