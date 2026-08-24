/**
 * `/submissions/:submissionId` — a batch as it is processed, polled live.
 *
 * §10.8 sets the interval at two seconds and, more importantly, sets when it
 * stops: at a terminal status. A page that keeps polling a finished submission
 * is a page that costs a request every two seconds for as long as somebody
 * leaves the tab open, which is exactly the tab that gets left open.
 *
 * The stopping is in `submissionQuery`'s `refetchInterval`, not here, because
 * the rule belongs to the resource rather than to one of its renderings.
 */

import { Link } from 'react-router-dom';
import { useParams } from 'react-router-dom';
import { useSubmission } from '../../api/hooks/catalogue';
import type { Submission } from '../../api/hooks/catalogue';
import { QueryState } from '../../components/QueryState';
import {
  Badge,
  Banner,
  Breadcrumbs,
  DefinitionList,
  StageRail,
  StatCard,
  Table,
} from '../../ui';
import type { Column } from '../../ui';
import { SUBMISSION_KIND_LABELS } from '../../lib/enums';
import type { SubmissionKind } from '../../lib/enums';
import { formatDateTime, formatNumber, humanise } from '../../lib/format';

/** The five stages the server reports, in the order it reports them. */
const STAGES = ['received', 'validating', 'applying', 'completed'] as const;

export function SubmissionDetailRoute() {
  const { submissionId = '' } = useParams();
  const query = useSubmission(submissionId);

  return (
    <div className="page">
      <Breadcrumbs crumbs={[{ label: 'Submission' }]} />
      <QueryState query={query} label="this submission">
        {(submission) => <SubmissionPanel submission={submission} />}
      </QueryState>
    </div>
  );
}

function SubmissionPanel({ submission }: { submission: Submission }) {
  const done = submission.status !== 'processing';
  const failed = submission.status === 'failed';

  const errorColumns: readonly Column<{ ref: string; reason: string }>[] = [
    { key: 'ref', header: 'Item', cell: (row) => <code>{row.ref}</code> },
    { key: 'reason', header: 'Rejected because', cell: (row) => row.reason },
  ];

  return (
    <>
      <div className="page__head">
        <h1 className="page__title">
          {SUBMISSION_KIND_LABELS[submission.kind as SubmissionKind] ?? humanise(submission.kind)}
        </h1>
        <p className="page__lede">
          Reference <code>{submission.reference}</code>, submitted{' '}
          {formatDateTime(submission.submitted_at)}.
        </p>
      </div>

      {/* One live region for the whole page. A reader on a screen reader is
          told when the status changes, and not on every two-second refetch of
          an unchanged number. */}
      <p aria-live="polite" className="visually-hidden">
        {done
          ? `Submission ${submission.status}.`
          : `Still processing, currently ${humanise(submission.stage)}.`}
      </p>

      <StageRail
        stages={STAGES}
        label="Submission progress"
        current={submission.stage}
        failed={failed}
        complete={submission.status === 'succeeded'}
      />

      {failed ? (
        <Banner kind="danger">
          This submission failed{submission.failure_code ? ` (${submission.failure_code})` : ''}.
          Nothing from it was applied in part — fix what is listed below and send it again.
        </Banner>
      ) : null}

      <DefinitionList
        items={[
          { term: 'Status', value: <Badge domain="submission" value={submission.status} /> },
          { term: 'Stage', value: humanise(submission.stage) },
          { term: 'Submitted', value: formatDateTime(submission.submitted_at) },
          { term: 'Completed', value: formatDateTime(submission.completed_at) },
        ]}
      />

      <div className="stat-grid">
        <StatCard label="Received" value={formatNumber(submission.counts.received)} />
        <StatCard label="Accepted" value={formatNumber(submission.counts.accepted)} />
        <StatCard label="Updated" value={formatNumber(submission.counts.updated)} />
        <StatCard label="Skipped" value={formatNumber(submission.counts.skipped)} />
        <StatCard label="Failed" value={formatNumber(submission.counts.failed)} />
      </div>

      {submission.errors.length > 0 ? (
        <section>
          <h2 className="eyebrow">Rejected items</h2>
          <p className="page__lede">
            {formatNumber(submission.error_count)} rejected
            {submission.error_count > submission.errors.length
              ? `, first ${submission.errors.length} shown`
              : ''}
            . Everything else in the batch was applied.
          </p>
          <Table
            caption="Rejected items"
            columns={errorColumns}
            rows={submission.errors}
            rowKey={(row) => row.ref}
          />
        </section>
      ) : null}

      {submission.kind === 'product_sync' ? (
        <p className="action-row">
          <Link to="/products">Back to the catalogue</Link>
        </p>
      ) : (
        <p className="action-row">
          <Link to="/events/submit">Submit more events</Link>
        </p>
      )}
    </>
  );
}
