/**
 * `/admin/status` — the live board. §10.8: 15 s, and it never stops.
 *
 * "Never stops" is the part worth defending. Every other poll on the console
 * has a terminal state to stop at; this one does not, because the page exists
 * to be left open on a second monitor and a board that quietly went stale an
 * hour ago is worse than no board — it reports health it has not checked.
 * `platformStatusQuery` therefore carries `refetchInterval` with no stop
 * condition, and this page renders the time of the last successful read so a
 * reader can see the polling is alive rather than trust that it is.
 *
 * Two endpoints are composed here: `/platform/status` for the aggregate board
 * and `/platform/failures` for the list beneath it. They are separate queries
 * rather than one, because the failure list is filtered and the board is not,
 * and refetching the board every time somebody narrows to `severity=critical`
 * would make the numbers above the filter flicker for no reason.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { failuresQuery, platformStatusQuery } from '../../api/hooks/platform';
import type { FailureRow, PlatformStatus } from '../../api/hooks/platform';
import { QueryState } from '../../components/QueryState';
import { Badge, FilterBar, Select, StatCard, Table, ToneBadge } from '../../ui';
import type { Column } from '../../ui';
import { ABSENT, formatAgo, formatDateTime, formatNumber, humanise } from '../../lib/format';

const AREA_OPTIONS = ['serving', 'ingestion', 'training', 'activation', 'capacity'].map(
  (value) => ({ value, label: humanise(value) }),
);

const SEVERITY_OPTIONS = ['info', 'warning', 'critical'].map((value) => ({
  value,
  label: humanise(value),
}));

export function AdminStatusRoute() {
  const [area, setArea] = useState('');
  const [severity, setSeverity] = useState('');
  const status = useQuery(platformStatusQuery);
  const failures = useQuery(failuresQuery({ area: area || undefined, severity: severity || undefined }));

  const columns: readonly Column<FailureRow>[] = [
    { key: 'when', header: 'When', cell: (row) => formatDateTime(row.occurred_at) },
    { key: 'area', header: 'Area', cell: (row) => humanise(row.area) },
    {
      key: 'severity',
      header: 'Severity',
      cell: (row) => <Badge domain="severity" value={row.severity} />,
    },
    { key: 'summary', header: 'What happened', cell: (row) => row.summary },
    {
      key: 'tenant',
      header: 'Tenant',
      // Null by default, and that is the server's choice rather than an
      // omission: a severity-ranked list that named tenants would be a league
      // table of who is struggling. When it is present, it links.
      cell: (row) =>
        row.tenant_id ? <Link to={`/admin/tenants/${row.tenant_id}`}>Open</Link> : ABSENT,
    },
    { key: 'reference', header: 'Reference', cell: (row) => <code>{row.reference}</code> },
  ];

  const filtered = area !== '' || severity !== '';

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Platform status</h1>
        <p className="page__lede">
          Refreshes every 15 seconds on its own.{' '}
          {status.dataUpdatedAt ? `Last read ${formatAgo(new Date(status.dataUpdatedAt).toISOString())}.` : ''}
        </p>
      </div>

      <QueryState query={status} label="the platform board">
        {(data) => <Board status={data} />}
      </QueryState>

      <h2 className="eyebrow">Recent failures</h2>
      <FilterBar
        onReset={
          filtered
            ? () => {
                setArea('');
                setSeverity('');
              }
            : undefined
        }
      >
        <Select
          label="Area"
          value={area}
          placeholder="Every area"
          options={AREA_OPTIONS}
          onChange={(event) => setArea(event.target.value)}
        />
        <Select
          label="Severity"
          value={severity}
          placeholder="Every severity"
          options={SEVERITY_OPTIONS}
          onChange={(event) => setSeverity(event.target.value)}
        />
      </FilterBar>

      <QueryState
        query={failures}
        shape="table"
        columns={columns.length}
        label="recent failures"
        isEmpty={(data) => data.total === 0 && !filtered}
        empty={{
          headline: 'No failures recorded',
          body: 'Nothing has failed terminally in the reporting window.',
        }}
      >
        {(data) => (
          <Table
            caption="Recent failures"
            columns={columns}
            rows={data.failures}
            rowKey={(row) => row.reference}
            empty="No failure matches those filters."
          />
        )}
      </QueryState>
    </div>
  );
}

function Board({ status }: { status: PlatformStatus }) {
  return (
    <>
      <div className="stat-grid">
        <StatCard label="Active tenants" value={formatNumber(status.active_tenants)} />
        <StatCard
          label="Serving availability"
          value={
            status.serving_availability === null
              ? ABSENT
              : `${(status.serving_availability * 100).toFixed(2)}%`
          }
          note={
            status.serving_availability === null
              ? 'Not measured in this window.'
              : `Over the last ${status.window_hours} hours.`
          }
        />
        <StatCard
          label="Ingestion lag"
          value={`${formatNumber(status.ingestion_lag_seconds)}s`}
          note="Oldest unprocessed submission."
        />
        <StatCard
          label={`Failures (${status.window_hours}h)`}
          value={formatNumber(status.failures_24h)}
        />
        <StatCard
          label="Training queue"
          value={`${formatNumber(status.training_queue.running)} running`}
          note={`${formatNumber(status.training_queue.waiting)} waiting, concurrency ${status.training_queue.concurrency}.`}
        />
        <StatCard
          label="Serving replicas"
          value={
            // `ready` is nullable and the difference matters: null means the
            // orchestrator did not answer, which is not the same as zero ready
            // replicas, and only one of those two is an outage.
            status.replicas.ready === null
              ? ABSENT
              : `${formatNumber(status.replicas.ready)} / ${formatNumber(status.replicas.desired)}`
          }
          note={
            status.replicas.ready === null
              ? 'Readiness was not reported.'
              : 'Ready against desired.'
          }
        />
      </div>

      {status.measurement_gaps.length > 0 ? (
        <>
          <h2 className="eyebrow">Measurement gaps</h2>
          <Table
            caption="Quantities that were not measured"
            columns={[
              {
                key: 'quantity',
                header: 'Quantity',
                cell: (row: { quantity: string }) => humanise(row.quantity),
              },
              {
                key: 'reason',
                header: 'Why',
                // The server's sentence, rendered as it came. UC-30's
                // alternative outcome is that a gap is identified rather than
                // hidden, and a console that wrote its own explanation here
                // would be hiding it behind a nicer one.
                cell: (row: { reason: string }) => row.reason,
              },
            ]}
            rows={status.measurement_gaps}
            rowKey={(row) => row.quantity}
          />
        </>
      ) : null}

      {status.failure_summary.length > 0 ? (
        <p className="action-row">
          {status.failure_summary.map((entry) => (
            <ToneBadge key={entry.area} tone="warn">
              {`${humanise(entry.area)}: ${entry.count}`}
            </ToneBadge>
          ))}
        </p>
      ) : null}

      <h2 className="eyebrow">Workload by tenant</h2>
      <Table
        caption="Workload by tenant"
        columns={[
          {
            key: 'tenant',
            header: 'Tenant',
            cell: (row: PlatformStatus['workload_by_tenant'][number]) => (
              <Link to={`/admin/tenants/${row.tenant_id}`}>{row.tenant_code}</Link>
            ),
          },
          {
            key: 'running',
            header: 'Training running',
            cell: (row: PlatformStatus['workload_by_tenant'][number]) =>
              formatNumber(row.running_jobs),
          },
          {
            key: 'queued',
            header: 'Training queued',
            cell: (row: PlatformStatus['workload_by_tenant'][number]) =>
              formatNumber(row.queued_jobs),
          },
          {
            key: 'replicas',
            header: 'Replicas',
            cell: (row: PlatformStatus['workload_by_tenant'][number]) =>
              `${formatNumber(row.ready_replicas)} / ${formatNumber(row.desired_replicas)}`,
          },
        ]}
        rows={status.workload_by_tenant}
        rowKey={(row) => row.tenant_id}
        empty="No tenant is running anything."
      />
    </>
  );
}
