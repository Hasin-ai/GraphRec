/**
 * `/models` — the registry, with the five summary counts above it.
 *
 * The counts come from `GET /v1/model-versions/summary` rather than from
 * counting the rows on this page, because the page is a filtered view and the
 * counts are about all of them. A client-side count would report "1 eligible"
 * on a filter showing one eligible version out of nine.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { modelSummaryQuery, modelVersionsQuery } from '../../api/hooks/model';
import type { ModelVersionListItem } from '../../api/hooks/model';
import { QueryState } from '../../components/QueryState';
import { Badge, FilterBar, Select, StatCard, Table, ToneBadge } from '../../ui';
import type { Column } from '../../ui';
import { formatDate, formatMetric, formatNumber } from '../../lib/format';

const STATUS_OPTIONS = [
  { value: 'registered', label: 'Registered' },
  { value: 'eligible', label: 'Eligible' },
  { value: 'active', label: 'Active' },
  { value: 'retired', label: 'Retired' },
  { value: 'archived', label: 'Archived' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'failed_deployment', label: 'Failed deployment' },
];

export function ModelsRoute() {
  const [status, setStatus] = useState('');
  const versions = useQuery(modelVersionsQuery(status || undefined));
  const summary = useQuery(modelSummaryQuery);

  const columns: readonly Column<ModelVersionListItem>[] = [
    {
      key: 'version',
      header: 'Version',
      cell: (row) => <Link to={`/models/${row.version_id}`}>v{row.version_number}</Link>,
    },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => <Badge domain="model" value={row.status} />,
    },
    {
      key: 'serving',
      header: 'Serving',
      // `serving` and `status === 'active'` are not the same fact. A version
      // can be active in the registry while its deployment is still rolling
      // out, and the difference is the whole reason both are shown.
      cell: (row) =>
        row.serving ? <ToneBadge tone="ok">live</ToneBadge> : <span aria-hidden="true">—</span>,
    },
    {
      key: 'ndcg',
      header: 'nDCG@10',
      cell: (row) => formatMetric(row.metrics.ndcg_at_10),
    },
    {
      key: 'recall',
      header: 'Recall@10',
      cell: (row) => formatMetric(row.metrics.recall_at_10),
    },
    {
      key: 'coverage',
      header: 'Coverage',
      cell: (row) => formatMetric(row.metrics.coverage),
    },
    { key: 'created', header: 'Trained', cell: (row) => formatDate(row.created_at) },
  ];

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Models</h1>
        <p className="page__lede">
          Every version a training run produced. One of them serves your recommendations; the rest
          are history you can return to.
        </p>
      </div>

      <QueryState query={summary} label="the model summary">
        {(data) => (
          <div className="stat-grid">
            <StatCard label="Active" value={formatNumber(data.active)} note="Serving now." />
            <StatCard
              label="Eligible"
              value={formatNumber(data.eligible)}
              note="Passed the quality floor; may be activated."
            />
            <StatCard label="Retired" value={formatNumber(data.retired)} />
            <StatCard label="Desired replicas" value={formatNumber(data.desired)} />
            <StatCard
              label="Failed deployment"
              value={formatNumber(data.failed_deployment)}
              note={data.failed_deployment > 0 ? 'Activated but did not come up.' : undefined}
            />
          </div>
        )}
      </QueryState>

      <FilterBar onReset={status ? () => setStatus('') : undefined}>
        <Select
          label="Status"
          value={status}
          placeholder="Any status"
          options={STATUS_OPTIONS}
          onChange={(event) => setStatus(event.target.value)}
        />
      </FilterBar>

      <QueryState
        query={versions}
        shape="table"
        columns={columns.length}
        label="model versions"
        isEmpty={(data) => data.total === 0 && !status}
        empty={{
          headline: 'No model versions yet',
          body: 'A successful training run registers the first one.',
        }}
      >
        {(data) => (
          <Table
            caption="Model versions"
            columns={columns}
            rows={data.versions}
            rowKey={(row) => row.version_id}
            empty="No version with that status."
          />
        )}
      </QueryState>
    </div>
  );
}
