import { billing } from "../../api";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDateTime, fmtNumber, fmtQuantity, humanize } from "../../lib/format";
import { quotaState } from "../../lib/quota";
import { Page } from "../../ui/Page";
import { Banner, Cell, DataTable, ErrorBanner, Meter, PanelTable, Skeleton, Tag } from "../../ui/primitives";
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
      <div className="usage-context"><span>{plan ? `${humanize(plan.plan_code)} plan` : 'Current usage period'}</span><span>Resets {fmtDateTime(usage.data.reset_at)}</span></div>
      {exhausted.length || approaching.length ? <Banner tone="warn" title={exhausted.length ? `${exhausted.length} ${exhausted.length === 1 ? 'limit is' : 'limits are'} exhausted` : 'Approaching a limit'}>
        {exhausted.length ? exhausted.map(d => humanize(d.type)).join(', ') + '.' : null}
        {approaching.length ? ` ${approaching.map(d => humanize(d.type)).join(', ')} ${approaching.length === 1 ? 'is' : 'are'} at or above 80%.` : null}
      </Banner> : <p className="footnote">{dims.length ? 'No measured usage is approaching an effective limit.' : 'No usage measurements were returned.'}</p>}
      <DataTable minWidth={740} columns={['Usage type', { label: 'Used', align: 'right' }, { label: 'Limit', align: 'right' }, 'Remaining', 'Status']}
        rows={dims.map(d => { const q = quotaState(d.used, d.limit); return <tr key={d.type}>
          <Cell>{humanize(d.type)}</Cell><Cell mono align="right">{fmtQuantity(d.used, d.unit)}</Cell>
          <Cell mono align="right">{d.limit === null ? 'No limit' : fmtQuantity(d.limit, d.unit)}</Cell>
          <td><Meter used={d.used} limit={d.limit} caption={q.remaining === null ? 'Not applicable' : `${fmtQuantity(q.remaining, d.unit)} remaining`} /></td>
          <td><Tag tone={q.tone}>{q.label}</Tag></td>
        </tr>; })} count={`${dims.length} usage types`} empty={{ title: 'No usage measurements', body: 'Refresh to check for new measurements.' }} />
      <p className="footnote">Period {fmtDateTime(usage.data.period_start)} – {fmtDateTime(usage.data.period_end)}. Last reconciled {fmtDateTime(usage.data.last_reconciled_at)}. {usage.data.project_defaults ? 'Default limits apply.' : 'Assigned plan and approved overrides apply.'}</p>
      <p className="footnote">These are ledger measurements. Stored-product and active-version usage can lag behind the catalog and model registry until the backend reconciles them.</p>
    </> : null}
    <UsageTrends />
    {subscription.error ? <ErrorBanner error={subscription.error} title="Subscription unavailable" onRetry={subscription.reload} /> : null}
    {plan ? <details className="details-section"><summary>Subscription · {humanize(plan.plan_code)} · {humanize(plan.status)}</summary>
      <p className="footnote">Plan defaults below. The usage table above includes effective overrides.</p>
      <PanelTable columns={['Plan limit', { label: 'Value', align: 'right' }]} rows={Object.entries(plan.limits).map(([key, value]) => <tr key={key}><Cell>{humanize(key)}</Cell><Cell mono align="right">{fmtNumber(value)}</Cell></tr>)} />
    </details> : null}
  </Page>;
}
