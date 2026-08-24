/**
 * `/training` — the runs, and the request dialog.
 *
 * The "Request training" button is the clearest gate-5 control in the console:
 * four separate conditions can block it (data volume, quota, concurrency,
 * cooldown), the server evaluates all four in `GET /v1/training-jobs/eligibility`
 * and sends back one `eligible` flag with one sentence. This page renders the
 * four sets of numbers so the reader can see *which* one is in the way, and
 * takes the enablement from `eligible` alone.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  startTraining,
  trainingEligibilityQuery,
  trainingJobsQuery,
  useTrainingMutation,
} from '../../api/hooks/model';
import type { TrainingEligibility, TrainingJob } from '../../api/hooks/model';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { GatedAction } from '../../components/gate5';
import { Badge, Banner, Dialog, FilterBar, Input, Select, StatCard, Table } from '../../ui';
import type { Column } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { formatDateTime, formatNumber } from '../../lib/format';

const STATE_OPTIONS = [
  { value: 'queued', label: 'Queued' },
  { value: 'training', label: 'Training' },
  { value: 'succeeded', label: 'Succeeded' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
];

export function TrainingRoute() {
  const [state, setState] = useState('');
  const [requesting, setRequesting] = useState(false);
  const jobs = useQuery(trainingJobsQuery(state || undefined));
  const eligibility = useQuery(trainingEligibilityQuery);

  const columns: readonly Column<TrainingJob>[] = [
    {
      key: 'ref',
      header: 'Run',
      cell: (row) => <Link to={`/training/${row.job_id}`}>{row.request_ref}</Link>,
    },
    { key: 'state', header: 'State', cell: (row) => <Badge domain="job" value={row.state} /> },
    { key: 'progress', header: 'Progress', cell: (row) => row.progress },
    { key: 'requested', header: 'Requested', cell: (row) => formatDateTime(row.requested_at) },
    { key: 'by', header: 'By', cell: (row) => row.requested_by ?? '—' },
    { key: 'completed', header: 'Completed', cell: (row) => formatDateTime(row.completed_at) },
  ];

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Training</h1>
        <p className="page__lede">
          A run turns the events you have sent into a model version. It is not instant and it is not
          continuous — you ask for one when you have enough new interactions to be worth learning
          from.
        </p>
      </div>

      <QueryState query={eligibility} label="training eligibility">
        {(data) => (
          <Eligibility eligibility={data} onRequest={() => setRequesting(true)} />
        )}
      </QueryState>

      <FilterBar onReset={state ? () => setState('') : undefined}>
        <Select
          label="State"
          value={state}
          placeholder="Any state"
          options={STATE_OPTIONS}
          onChange={(event) => setState(event.target.value)}
        />
      </FilterBar>

      <QueryState
        query={jobs}
        shape="table"
        columns={columns.length}
        label="training runs"
        isEmpty={(data) => data.total === 0 && !state}
        empty={{
          headline: 'No training runs yet',
          body: 'Once you have enough interaction data, request the first one. It takes a while — you can leave the page.',
        }}
      >
        {(data) => (
          <Table
            caption="Training runs"
            columns={columns}
            rows={data.jobs}
            rowKey={(row) => row.job_id}
            empty="No run in that state."
          />
        )}
      </QueryState>

      {requesting ? <RequestDialog onClose={() => setRequesting(false)} /> : null}
    </div>
  );
}

/**
 * The four cards, then the one control.
 *
 * Each card states the limit and the position against it, because "you cannot
 * train yet" is useless and "you have 812 of the 1,000 sequences required" is
 * a plan.
 */
function Eligibility({
  eligibility,
  onRequest,
}: {
  eligibility: TrainingEligibility;
  onRequest: () => void;
}) {
  const { interaction_data: data, quota, concurrency, cooldown } = eligibility;

  return (
    <section className="stack">
      <div className="stat-grid">
        <StatCard
          label="Interaction data"
          value={`${formatNumber(data.sequences)} sequences`}
          note={
            data.sufficient
              ? 'Enough to train on.'
              : `${formatNumber(data.required)} required.`
          }
        />
        <StatCard
          label="Runs this month"
          value={quota.limit === null ? `${formatNumber(quota.used)} used` : `${formatNumber(quota.used)} of ${formatNumber(quota.limit)}`}
          note={
            quota.limit === null
              ? 'No limit on your plan.'
              : `${formatNumber(quota.remaining ?? 0)} left, resets ${quota.resets_at}.`
          }
        />
        <StatCard
          label="Concurrent runs"
          value={formatNumber(concurrency.limit)}
          note={`At once, per ${concurrency.scope}.`}
        />
        <StatCard
          label="Cooldown"
          value={cooldown.active ? `${Math.ceil(cooldown.seconds_remaining / 60)} min` : 'Clear'}
          note={
            cooldown.active
              ? 'Since the last run started.'
              : `${Math.round(cooldown.window_seconds / 60)} minutes between runs.`
          }
        />
      </div>

      <div className="action-row">
        <GatedAction
          label="Request training"
          allowed={eligibility.eligible}
          reason={eligibility.reason}
          variant="primary"
          onClick={onRequest}
        />
      </div>
    </section>
  );
}

function RequestDialog({ onClose }: { onClose: () => void }) {
  const [windowDays, setWindowDays] = useState('90');
  const [epochs, setEpochs] = useState('20');
  const [ref, setRef] = useState('');
  const mutation = useTrainingMutation((body: S['RequestTrainingRequest']) => startTraining(body));
  const form = useSubmit<TrainingJob>(
    (body: S['RequestTrainingRequest']) => mutation.mutateAsync(body),
    onClose,
  );

  return (
    <Dialog
      title="Request training"
      onClose={onClose}
      confirmLabel="Start run"
      busy={form.pending}
      onConfirm={() =>
        form.submit({
          interaction_window_days: Number(
            windowDays,
          ) as S['RequestTrainingRequest']['interaction_window_days'],
          max_epochs: Number(epochs) as S['RequestTrainingRequest']['max_epochs'],
          model_type: 'DGSR',
          request_ref: ref.trim() || `run-${new Date().toISOString().slice(0, 10)}`,
        })
      }
      wide
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <p className="page__lede">
        The defaults are the ones we would pick. Change them only if you have a reason —
        a longer window learns from more history and takes longer.
      </p>
      <Select
        label="Interaction window"
        value={windowDays}
        options={[
          { value: '30', label: 'Last 30 days' },
          { value: '90', label: 'Last 90 days' },
          { value: '180', label: 'Last 180 days' },
        ]}
        error={form.fieldErrors.interaction_window_days}
        onChange={(event) => setWindowDays(event.target.value)}
      />
      <Select
        label="Maximum epochs"
        value={epochs}
        options={[
          { value: '10', label: '10 — quick' },
          { value: '20', label: '20 — default' },
          { value: '40', label: '40 — thorough' },
        ]}
        error={form.fieldErrors.max_epochs}
        onChange={(event) => setEpochs(event.target.value)}
      />
      <Input
        label="Label"
        value={ref}
        error={form.fieldErrors.request_ref}
        onChange={(event) => setRef(event.target.value)}
        hint="How you will recognise this run in the list later."
      />
    </Dialog>
  );
}
