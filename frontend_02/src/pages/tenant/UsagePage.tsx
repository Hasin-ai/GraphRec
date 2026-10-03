import { billing } from "../../api";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDate, fmtDateTime, fmtNumber, fmtQuantity, humanize } from "../../lib/format";
import { quotaMessage, quotaState } from "../../lib/quota";
import { Page } from "../../ui/Page";
import { Cell, DataTable, ErrorBanner, Meter, PanelTable, Skeleton, Tag } from "../../ui/primitives";
import { UsageTrends } from "./UsageTrends";

export function UsagePage() {
  const { can } = useSession();
  const usage = useResource(() => billing.usage(), []);
  const subscription = useResource(() => can('billing:read') ? billing.subscription() : Promise.resolve(null), [can('billing:read')]);
  const dims = usage.data?.dimensions ?? [];
  const exhausted = dims.filter(d => quotaState(d.used, d.limit).status === 'exhausted');
  const approaching = dims.filter(d => quotaState(d.used, d.limit).status === 'approaching');
  const plan = subscription.data;
  return <Page crumbs={[{ label: 'Home', to: '/home' }, { label: 'Usage & Quotas' }]} title="Usage & Quotas" subtitle="Consumption and effective limits for this tenant." actions={[{ label: 'Refresh', disabled: usage.loading, onClick: () => { void usage.reload(); void subscription.reload(); } }]}>
    {usage.error ? <ErrorBanner error={usage.error} onRetry={usage.reload} /> : null}
    {!usage.data && usage.loading ? <Skeleton /> : null}
    {usage.data ? <>
      <div className="usage-context"><span>{plan ? `${humanize(plan.plan_code)} plan` : 'Current usage period'}</span><span>Resets {fmtDate(usage.data.reset_at)}</span></div>
      {exhausted.length || approaching.length ? <div className="ov-alerts flat">{[...exhausted, ...approaching].map(d => { const msg = quotaMessage(d.type, d.used, d.limit); const ex = quotaState(d.used, d.limit).status === 'exhausted'; return <div key={d.type} className={`ov-alert ${ex ? 'danger' : 'warn'}`} role={ex ? 'alert' : 'status'}><div><strong>{msg.title}</strong><span>{msg.body}</span></div></div>; })}</div> : <p className="footnote">{dims.length ? 'No measured usage is approaching an effective limit.' : 'No usage measurements were returned.'}</p>}
      <DataTable minWidth={740} columns={['Usage type', { label: 'Used', align: 'right' }, { label: 'Limit', align: 'right' }, 'Remaining', 'Status']}
        rows={dims.map(d => { const q = quotaState(d.used, d.limit); return <tr key={d.type}>
          <Cell>{humanize(d.type).replace(/ bytes$/, '')}</Cell><Cell mono align="right">{fmtQuantity(d.used, d.unit)}</Cell>
          <Cell mono align="right">{d.limit === null ? 'No limit' : fmtQuantity(d.limit, d.unit)}</Cell>
          <td>{d.limit === null ? <span className="td-muted">Tracked, no limit</span> : d.used > d.limit ? <><Meter used={d.limit} limit={d.limit} caption="" /><span className="over-by">{fmtQuantity(d.used - d.limit, d.unit)} over the limit</span></> : <Meter used={d.used} limit={d.limit} caption={`${fmtQuantity(q.remaining ?? 0, d.unit)} remaining`} />}</td>
          <td>{d.limit === null ? <Tag tone="neu">{q.label}</Tag> : <Tag tone={q.tone}>{d.limit !== null && d.used > d.limit ? 'Over limit' : q.label}</Tag>}</td>
        </tr>; })} count={`${dims.length} usage types`} empty={{ title: 'No usage measurements', body: 'Refresh to check for new measurements.' }} />
      <p className="footnote">Period {fmtDate(usage.data.period_start)} – {fmtDate(usage.data.period_end)}. Last updated {fmtDateTime(usage.data.last_reconciled_at)}. {usage.data.project_defaults ? 'Default limits apply.' : 'Assigned plan and approved overrides apply.'}{plan && plan.period_end && Math.abs(Date.parse(plan.period_end) - Date.parse(usage.data.period_end)) > 86_400_000 ? <> Note: your subscription period ends {fmtDate(plan.period_end)}, but usage counters reset {fmtDate(usage.data.reset_at)}. Limits follow the usage reset.</> : null}</p>
      <p className="footnote">Product and model-version counts can lag a few minutes behind the catalog and model list.</p>
    </> : null}
    <UsageTrends />
    {subscription.error ? <ErrorBanner error={subscription.error} title="Subscription unavailable" onRetry={subscription.reload} /> : null}
    {plan ? <details className="details-section"><summary>Subscription · {humanize(plan.plan_code)} · {humanize(plan.status)}</summary>
      <p className="footnote">Plan defaults below. The usage table above includes effective overrides.</p>
      <PanelTable columns={['Plan limit', { label: 'Value', align: 'right' }]} rows={Object.entries(plan.limits).map(([key, value]) => <tr key={key}><Cell>{humanize(key)}</Cell><Cell mono align="right">{fmtNumber(value)}</Cell></tr>)} />
    </details> : null}
  </Page>;
}
