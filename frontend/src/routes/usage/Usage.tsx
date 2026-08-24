/**
 * `/usage` — what you have used this period, against what you are entitled to.
 *
 * The one rule that shapes this page: a quantity the platform could not
 * measure is an em dash and a sentence, never a zero. `measurement_status`
 * exists so the difference between "you sent no events" and "we could not
 * count your events" survives the trip to the browser, and a page that renders
 * both as 0 throws that away at the last step.
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { subscriptionQuery, usageQuery, usageTrendsQuery } from '../../api/hooks/operations';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { Banner, Select, Table } from '../../ui';
import type { Column } from '../../ui';
import { MEASUREMENT_STATUS_LABELS } from '../../lib/enums';
import type { MeasurementStatus } from '../../lib/enums';
import { ABSENT, formatNumber, humanise } from '../../lib/format';

type UsageItem = S['UsageItemBody'];
type TrendRow = S['UsageTrendRowBody'];

const PERIOD_OPTIONS = [
  { value: '3', label: 'Last 3 periods' },
  { value: '6', label: 'Last 6 periods' },
  { value: '12', label: 'Last 12 periods' },
];

export function UsageRoute() {
  const [periods, setPeriods] = useState('6');
  const usage = useQuery(usageQuery);
  const trends = useQuery(usageTrendsQuery(Number(periods)));
  const subscription = useQuery(subscriptionQuery);

  const columns: readonly Column<UsageItem>[] = [
    { key: 'type', header: 'Resource', cell: (row) => humanise(row.usage_type) },
    {
      key: 'measured',
      header: 'Used',
      cell: (row) => <Measured item={row} />,
    },
    {
      key: 'limit',
      header: 'Included',
      cell: (row) =>
        row.effective_limit === null ? 'Unlimited' : formatNumber(row.effective_limit),
    },
    {
      key: 'remaining',
      header: 'Remaining',
      cell: (row) => (row.remaining === null ? ABSENT : formatNumber(row.remaining)),
    },
    {
      key: 'source',
      header: 'Limit from',
      // "override" is worth surfacing: it means somebody on the platform side
      // changed this tenant's limit away from the plan, and the reader would
      // otherwise be comparing against a number their plan does not state.
      cell: (row) => (row.limit_source === 'override' ? 'Agreed with us' : 'Your plan'),
    },
    { key: 'reset', header: 'Resets', cell: (row) => row.reset },
  ];

  const trendColumns: readonly Column<TrendRow>[] = [
    { key: 'label', header: 'Period', cell: (row) => row.label },
    ...(['events', 'recommendations', 'training', 'storage'] as const).map((key) => ({
      key,
      header: humanise(key),
      cell: (row: TrendRow) => row.quantities[key] ?? ABSENT,
    })),
  ];

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Usage</h1>
        <p className="page__lede">
          What this organisation has used, and what its plan includes. Figures are the platform's
          own measurements; where one is missing, it says so rather than showing a zero.
        </p>
      </div>

      <QueryState query={subscription} label="your plan">
        {(plan) => (
          <Banner kind="info">
            You are on <strong>{plan.plan_name}</strong>
            {plan.description ? ` — ${plan.description}` : ''}.
          </Banner>
        )}
      </QueryState>

      <QueryState
        query={usage}
        shape="table"
        columns={columns.length}
        label="this period's usage"
        isEmpty={(data) => data.items.length === 0}
        empty={{
          headline: 'Nothing measured yet',
          body: 'Usage appears once the first period has been rolled up.',
        }}
      >
        {(data) => (
          <>
            <h2 className="eyebrow">{data.period.label}</h2>
            <Table
              caption={`Usage for ${data.period.label}`}
              columns={columns}
              rows={data.items}
              rowKey={(row) => row.usage_type}
            />
            {data.footnote ? <p className="page__lede">{data.footnote}</p> : null}
          </>
        )}
      </QueryState>

      <section>
        <h2 className="eyebrow">Over time</h2>
        <Select
          label="Show"
          value={periods}
          options={PERIOD_OPTIONS}
          onChange={(event) => setPeriods(event.target.value)}
        />
        <QueryState
          query={trends}
          shape="table"
          columns={trendColumns.length}
          label="usage over time"
          isEmpty={(data) => data.rows.length === 0}
          empty={{
            headline: 'No history yet',
            body: 'Once a second period closes there is something to compare against.',
          }}
        >
          {(data) => (
            <Table
              caption="Usage by period"
              columns={trendColumns}
              rows={data.rows}
              rowKey={(row) => row.period}
            />
          )}
        </QueryState>
      </section>
    </div>
  );
}

/** A measured quantity, or the reason there is not one. */
function Measured({ item }: { item: UsageItem }) {
  if (item.measured !== null && item.measurement_status === 'measured') {
    return <>{item.measured}</>;
  }
  return (
    <>
      <span aria-hidden="true">{ABSENT}</span>
      <span className="gated__reason">
        {MEASUREMENT_STATUS_LABELS[item.measurement_status as MeasurementStatus] ??
          humanise(item.measurement_status)}
      </span>
    </>
  );
}
