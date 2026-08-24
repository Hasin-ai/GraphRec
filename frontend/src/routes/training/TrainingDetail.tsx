/**
 * `/training/:jobId` — one run, polled every two seconds until it settles.
 *
 * The rail draws `job.stages` rather than a constant in this bundle. The
 * server sends the stage list with every response for exactly this reason: a
 * tenth stage is a backend change and a redeploy, not a frontend release.
 */

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  cancelTraining,
  isTerminal,
  trainingMetricsQuery,
  useTrainingJob,
  useTrainingMutation,
} from '../../api/hooks/model';
import type { TrainingJob } from '../../api/hooks/model';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { GatedAction } from '../../components/gate5';
import {
  Badge,
  Banner,
  Breadcrumbs,
  DefinitionList,
  Dialog,
  StageRail,
  StatCard,
  Table,
  Textarea,
} from '../../ui';
import type { Column } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { formatDateTime, formatMetric, formatNumber, humanise } from '../../lib/format';

export function TrainingDetailRoute() {
  const { jobId = '' } = useParams();
  const query = useTrainingJob(jobId);

  return (
    <div className="page">
      <Breadcrumbs
        crumbs={[{ label: 'Training', to: '/training' }, { label: query.data?.request_ref ?? 'Run' }]}
      />
      <QueryState query={query} label="this training run">
        {(job) => <JobPanel job={job} />}
      </QueryState>
    </div>
  );
}

function JobPanel({ job }: { job: TrainingJob }) {
  const [cancelling, setCancelling] = useState(false);
  const settled = isTerminal(job.state);

  return (
    <>
      <div className="page__head">
        <h1 className="page__title">{job.request_ref}</h1>
        <p className="page__lede">
          Requested {formatDateTime(job.requested_at)}
          {job.requested_by ? ` by ${job.requested_by}` : ''}.
        </p>
      </div>

      {/* Announced once per change rather than once per poll: the text is
          derived from state and stage, both of which are stable between
          refetches that change nothing. */}
      <p aria-live="polite" className="visually-hidden">
        {settled
          ? `Run ${job.state}.`
          : `Run in progress, stage ${humanise(job.stages[job.stage_index] ?? job.state)}.`}
      </p>

      <StageRail
        stages={job.stages}
        current={job.stages[job.stage_index] ?? job.state}
        failed={job.state === 'failed'}
        complete={job.state === 'succeeded'}
      />

      {job.state === 'failed' ? (
        <Banner kind="danger">
          {job.failure_reason ?? 'This run failed.'}
          {job.error_reference ? ` Reference: ${job.error_reference}.` : ''}
        </Banner>
      ) : null}
      {job.state === 'cancelled' ? (
        <Banner kind="info">
          Cancelled{job.cancel_reason ? `: ${job.cancel_reason}` : ''}. Nothing was registered.
        </Banner>
      ) : null}
      {job.blocked_reason ? <Banner kind="warning">{job.blocked_reason}</Banner> : null}

      <DefinitionList
        items={[
          { term: 'State', value: <Badge domain="job" value={job.state} /> },
          { term: 'Progress', value: job.progress },
          { term: 'Interaction window', value: `${job.interaction_window_days} days` },
          { term: 'Maximum epochs', value: formatNumber(job.max_epochs) },
          { term: 'Completed', value: formatDateTime(job.completed_at) },
          { term: 'Note', value: job.note || '—' },
        ]}
      />

      {job.snapshot ? (
        <section>
          <h2 className="eyebrow">What it trained on</h2>
          <div className="stat-grid">
            <StatCard label="Sequences" value={formatNumber(job.snapshot.sequence_count)} />
            <StatCard label="Events" value={formatNumber(job.snapshot.event_count)} />
            <StatCard label="Products" value={formatNumber(job.snapshot.product_count)} />
            <StatCard
              label="Data up to"
              value={formatDateTime(job.snapshot.cutoff_at)}
              note="Anything after this cutoff is not in this model."
            />
          </div>
        </section>
      ) : null}

      <div className="action-row">
        <GatedAction
          label="Cancel run"
          allowed={job.can_cancel}
          reason={
            settled
              ? 'This run has already finished.'
              : 'This run cannot be cancelled at its current stage.'
          }
          variant="secondary"
          onClick={() => setCancelling(true)}
        />
      </div>

      <Metrics jobId={job.job_id} enabled={job.state === 'succeeded' || job.stage_index >= 5} />

      {cancelling ? <CancelDialog job={job} onClose={() => setCancelling(false)} /> : null}
    </>
  );
}

/**
 * Per-epoch metrics, fetched only once the run has something to report.
 *
 * `enabled` is a stage check rather than a state check because evaluation
 * writes metrics before the run finishes, and watching them arrive is most of
 * the reason to keep this page open.
 */
function Metrics({ jobId, enabled }: { jobId: string; enabled: boolean }) {
  const query = useQuery({ ...trainingMetricsQuery(jobId), enabled });
  if (!enabled) return null;

  const columns: readonly Column<S['TrainingMetricBody']>[] = [
    { key: 'epoch', header: 'Epoch', cell: (row) => formatNumber(row.epoch) },
    { key: 'metric', header: 'Metric', cell: (row) => humanise(row.metric_name) },
    { key: 'value', header: 'Value', cell: (row) => formatMetric(row.value) },
  ];

  return (
    <section>
      <h2 className="eyebrow">Metrics</h2>
      <QueryState
        query={query}
        shape="table"
        columns={columns.length}
        label="training metrics"
        isEmpty={(data) => data.metrics.length === 0}
        empty={{
          headline: 'No metrics yet',
          body: 'They appear once evaluation runs.',
        }}
      >
        {(data) => (
          <Table
            caption="Per-epoch metrics"
            columns={columns}
            rows={data.metrics}
            rowKey={(row) => `${row.epoch}-${row.metric_name}`}
          />
        )}
      </QueryState>
    </section>
  );
}

/**
 * Cancelling requires four characters of reason, enforced here and on the
 * server. Both, because the console is not the only client and the audit row
 * outlives whichever one wrote it.
 */
function CancelDialog({ job, onClose }: { job: TrainingJob; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const mutation = useTrainingMutation((body: S['CancelTrainingRequest']) =>
    cancelTraining(job.job_id, body),
  );
  const form = useSubmit<TrainingJob>(
    (body: S['CancelTrainingRequest']) => mutation.mutateAsync(body),
    onClose,
  );

  return (
    <Dialog
      title={`Cancel ${job.request_ref}`}
      onClose={onClose}
      confirmLabel="Cancel run"
      confirmVariant="danger"
      cancelLabel="Keep running"
      busy={form.pending}
      confirmDisabled={reason.trim().length < 4}
      onConfirm={() => form.submit({ reason: reason.trim() })}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <p className="page__lede">
        The work done so far is discarded and no model version is registered. Your active model is
        untouched.
      </p>
      <Textarea
        label="Reason"
        required
        rows={3}
        value={reason}
        error={form.fieldErrors.reason}
        onChange={(event) => setReason(event.target.value)}
      />
    </Dialog>
  );
}
