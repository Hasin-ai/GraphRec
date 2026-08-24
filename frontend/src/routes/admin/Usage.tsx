/**
 * `/admin/usage` — every tenant's aggregates, in one table.
 *
 * The tenant-facing `/usage` page answers "what have I used". This one answers
 * "who is using what", which is a different question with one shared rule: a
 * quantity that was not measured renders as an em dash and the reason, never as
 * a zero. Across a whole estate that matters more, not less — a zero here is
 * read as an idle tenant, and an idle tenant is a churn conversation.
 *
 * `quantity` arrives as a string and stays one. See `formatQuantity`.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { platformUsageQuery } from '../../api/hooks/platform';
import type { UsageRow } from '../../api/hooks/platform';
import { QueryState } from '../../components/QueryState';
import { FilterBar, Select, Table } from '../../ui';
import type { Column } from '../../ui';
import { MEASUREMENT_STATUS_LABELS } from '../../lib/enums';
import type { UsageType } from '../../lib/enums';
import { ABSENT, formatQuantity, humanise } from '../../lib/format';

// `satisfies` rather than a hand-typed list of strings: `UsageType` is
// generated from the backend enum, so adding a seventh usage type there breaks
// this line rather than quietly leaving it out of the filter.
const USAGE_TYPE_OPTIONS = (
  [
    'events',
    'recommendations',
    'training',
    'products',
    'storage',
    'service_capacity',
  ] satisfies UsageType[]
).map((value) => ({ value, label: humanise(value) }));

export function AdminUsageRoute() {
  const [period, setPeriod] = useState('');
  const [usageType, setUsageType] = useState('');
  const query = useQuery(
    platformUsageQuery({ period: period || undefined, usage_type: usageType || undefined }),
  );

  const columns: readonly Column<UsageRow>[] = [
    {
      key: 'tenant',
      header: 'Tenant',
      cell: (row) => <Link to={`/admin/tenants/${row.tenant_id}`}>{row.tenant_code}</Link>,
    },
    { key: 'period', header: 'Period', cell: (row) => row.period },
    { key: 'type', header: 'Resource', cell: (row) => humanise(row.usage_type) },
    {
      key: 'quantity',
      header: 'Quantity',
      cell: (row) =>
        row.quantity !== null && row.measurement_status === 'measured' ? (
          formatQuantity(row.quantity)
        ) : (
          <>
            <span aria-hidden="true">{ABSENT}</span>
            <span className="gated__reason">
              {MEASUREMENT_STATUS_LABELS[row.measurement_status] ??
                humanise(row.measurement_status)}
            </span>
          </>
        ),
    },
  ];

  const filtered = period !== '' || usageType !== '';

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Usage across the estate</h1>
        <p className="page__lede">
          Rolled-up figures per tenant and period. A figure the platform could not measure says
          so; it is not reported as nothing used.
        </p>
      </div>

      <FilterBar
        onReset={
          filtered
            ? () => {
                setPeriod('');
                setUsageType('');
              }
            : undefined
        }
      >
        <Select
          label="Resource"
          value={usageType}
          placeholder="Every resource"
          options={USAGE_TYPE_OPTIONS}
          onChange={(event) => setUsageType(event.target.value)}
        />
        <Select
          label="Period"
          value={period}
          placeholder="Current period"
          // The periods offered are the ones present in the answer, so the
          // filter can never name a period with nothing behind it.
          options={periodOptions(query.data?.rows)}
          onChange={(event) => setPeriod(event.target.value)}
        />
      </FilterBar>

      <QueryState
        query={query}
        shape="table"
        columns={columns.length}
        label="usage across tenants"
        isEmpty={(data) => data.total === 0 && !filtered}
        empty={{
          headline: 'Nothing rolled up yet',
          body: 'Figures appear once the first aggregation has run for a period.',
        }}
      >
        {(data) => (
          <>
            <Table
              caption="Usage by tenant"
              columns={columns}
              rows={data.rows}
              rowKey={(row) => `${row.tenant_id}-${row.period}-${row.usage_type}`}
              empty="No usage matches those filters."
            />
            <p className="page__lede">
              Showing {data.rows.length} of {data.total}.
            </p>
          </>
        )}
      </QueryState>
    </div>
  );
}

function periodOptions(rows: readonly UsageRow[] | undefined) {
  const periods = [...new Set((rows ?? []).map((row) => row.period))].sort().reverse();
  return periods.map((value) => ({ value, label: value }));
}
