/**
 * `/service-status` — the live board, refreshed every fifteen seconds.
 *
 * §10.8 says this one never stops polling, and that is the right call for a
 * page whose entire purpose is to be left open on a second monitor during an
 * incident. Fifteen seconds is slow enough to be cheap and fast enough that
 * nobody reaches for the reload button, which is the failure mode that makes
 * people distrust a status page.
 *
 * `serving_previous` gets the most prominent treatment here. It is true
 * exactly when a version was asked for and a different one is answering — the
 * state a failed activation leaves behind, and the one question this page
 * exists to answer.
 */

import { useQuery } from '@tanstack/react-query';
import {
  deploymentQuery,
  metricsSummaryQuery,
  replicasQuery,
  servingErrorsQuery,
} from '../../api/hooks/operations';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { Badge, Banner, DefinitionList, StatCard, Table, ToneBadge } from '../../ui';
import type { Column } from '../../ui';
import { MEASUREMENT_STATUS_LABELS } from '../../lib/enums';
import type { MeasurementStatus } from '../../lib/enums';
import { ABSENT, formatAgo, formatDateTime, formatNumber, formatPercent } from '../../lib/format';

export function ServiceStatusRoute() {
  const deployment = useQuery(deploymentQuery);
  const metrics = useQuery(metricsSummaryQuery(24));
  const replicas = useQuery(replicasQuery);
  const errors = useQuery(servingErrorsQuery);

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Service status</h1>
        <p className="page__lede">
          What is serving your recommendations right now. This page refreshes itself every fifteen
          seconds; you do not need to reload it.
        </p>
      </div>

      <QueryState query={deployment} label="the deployment">
        {(data) => <Deployment data={data} />}
      </QueryState>

      <section>
        <h2 className="eyebrow">Last 24 hours</h2>
        <QueryState query={metrics} label="serving metrics">
          {(data) => <Metrics data={data} />}
        </QueryState>
      </section>

      <section>
        <h2 className="eyebrow">Capacity</h2>
        <QueryState
          query={replicas}
          shape="table"
          columns={4}
          label="replicas"
          isEmpty={(data) => data.replicas.length === 0}
          empty={{
            headline: 'Nothing running',
            body: 'No replica is serving. If you have an active version, it is still coming up.',
          }}
        >
          {(data) => <Replicas data={data} />}
        </QueryState>
      </section>

      <section>
        <h2 className="eyebrow">Recent errors</h2>
        <QueryState
          query={errors}
          shape="table"
          columns={4}
          label="recent serving errors"
          isEmpty={(data) => data.errors.length === 0}
          empty={{
            headline: 'No recent errors',
            body: 'Nothing has failed while serving recommendations.',
          }}
        >
          {(data) => <Errors data={data} />}
        </QueryState>
      </section>
    </div>
  );
}

function Deployment({ data }: { data: S['DeploymentResponse'] }) {
  return (
    <>
      {data.serving_previous ? (
        <Banner kind="warning">
          Version {data.desired_version?.version_number ?? '?'} was activated but version{' '}
          {data.active_version?.version_number ?? '?'} is still answering. Recommendations are being
          served — from the older model.
        </Banner>
      ) : null}

      <div className="stat-grid">
        <StatCard
          label="Serving"
          value={
            data.active_version ? `v${data.active_version.version_number}` : 'Nothing'
          }
          note={data.active_version ? undefined : 'No model version is active yet.'}
        />
        <StatCard
          label="State"
          value={<Badge domain="deploy" value={data.state} />}
          note={
            data.last_transition_at ? `Changed ${formatAgo(data.last_transition_at)}` : undefined
          }
        />
        <StatCard
          label="Replicas"
          value={`${formatNumber(data.ready_replicas)} of ${formatNumber(data.desired_replicas)}`}
          note="Ready of desired."
        />
        <StatCard
          label="Response time"
          value={data.latency_p95_ms === null ? ABSENT : `${formatNumber(data.latency_p95_ms)} ms`}
          note={<Freshness status={data.measurement_status} seconds={data.measurement_freshness_seconds} />}
        />
        <StatCard
          label="Fallbacks"
          value={data.fallback_rate === null ? ABSENT : formatPercent(data.fallback_rate)}
          note="Requests answered by the popularity fallback instead of the model."
        />
        <StatCard
          label="Errors, 24h"
          value={formatNumber(data.recent_error_count_24h)}
        />
      </div>

      <DefinitionList
        items={[
          {
            term: 'Active version',
            value: data.active_version ? `v${data.active_version.version_number}` : ABSENT,
          },
          {
            term: 'Requested version',
            value: data.desired_version ? `v${data.desired_version.version_number}` : ABSENT,
          },
          { term: 'Last change', value: formatDateTime(data.last_transition_at) },
        ]}
      />
    </>
  );
}

function Metrics({ data }: { data: S['MetricsSummaryResponse'] }) {
  return (
    <div className="stat-grid">
      <StatCard label="Requests" value={formatNumber(data.requests)} />
      <StatCard
        label="Availability"
        value={data.availability === null ? ABSENT : formatPercent(data.availability)}
        note={<Freshness status={data.measurement_status} seconds={data.measurement_freshness_seconds} />}
      />
      <StatCard
        label="Response time"
        value={data.latency_p95_ms === null ? ABSENT : `${formatNumber(data.latency_p95_ms)} ms`}
        note="95th percentile."
      />
      <StatCard label="Errors" value={formatNumber(data.errors)} />
    </div>
  );
}

function Replicas({ data }: { data: S['DeploymentReplicasResponse'] }) {
  const columns: readonly Column<S['ReplicaBody']>[] = [
    { key: 'ref', header: 'Replica', cell: (row) => <code>{row.replica_ref}</code> },
    {
      key: 'ready',
      header: 'Ready',
      cell: (row) =>
        row.ready ? <ToneBadge tone="ok">ready</ToneBadge> : <ToneBadge tone="warn">{row.status}</ToneBadge>,
    },
    { key: 'started', header: 'Started', cell: (row) => formatDateTime(row.started_at) },
    { key: 'observed', header: 'Last seen', cell: (row) => formatAgo(row.observed_at) },
  ];

  return (
    <Table
      caption="Replicas"
      columns={columns}
      rows={data.replicas}
      rowKey={(row) => row.replica_ref}
    />
  );
}

function Errors({ data }: { data: S['ServingErrorsResponse'] }) {
  const columns: readonly Column<S['ServingErrorBody']>[] = [
    { key: 'when', header: 'When', cell: (row) => formatDateTime(row.occurred_at) },
    { key: 'class', header: 'Kind', cell: (row) => row.error_class },
    { key: 'reason', header: 'What happened', cell: (row) => row.reason },
    // The reference is here so support can be quoted a specific failure rather
    // than "it was broken around three".
    { key: 'ref', header: 'Reference', cell: (row) => <code>{row.reference}</code> },
  ];

  return (
    <Table
      caption="Recent serving errors"
      columns={columns}
      rows={data.errors}
      rowKey={(row) => row.reference}
    />
  );
}

/** How stale a measurement is, or why there is not one. */
function Freshness({ status, seconds }: { status: string; seconds: number | null }) {
  if (status !== 'measured') {
    return (
      <>{MEASUREMENT_STATUS_LABELS[status as MeasurementStatus] ?? status}</>
    );
  }
  if (seconds === null) return null;
  return <>Measured {seconds < 60 ? 'just now' : `${Math.round(seconds / 60)} min ago`}.</>;
}
