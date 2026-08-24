/**
 * `/models/:versionId` — one version, and the three-way comparison.
 *
 * The three columns are this version, the platform's popularity baseline over
 * the same held-out rows, and whatever is active today. The baseline column is
 * the honest one: a model that cannot beat "recommend what is popular" is not
 * worth serving, and without the column that question never gets asked.
 *
 * When nothing is active, or this version *is* the active one, the third
 * column is absent and renders as an em dash. The server sends `null` and the
 * page renders the absence; neither invents a comparison.
 */

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  activateVersion,
  archiveVersion,
  modelVersionQuery,
  rollbackModel,
  useModelMutation,
} from '../../api/hooks/model';
import type { ModelVersion } from '../../api/hooks/model';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { GatedAction } from '../../components/gate5';
import { Badge, Banner, Breadcrumbs, DefinitionList, Dialog, Textarea } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { ABSENT, formatDateTime, formatMetric } from '../../lib/format';

type Measures = S['VersionMeasuresBody'];
type Comparison = S['VersionComparisonBody'];

/** The four measures, in the order the comparison table lists them. */
const MEASURES = [
  {
    key: 'ndcg_at_10' as const,
    label: 'nDCG@10',
    hint: 'Whether the right items are near the top of the ten.',
  },
  {
    key: 'recall_at_10' as const,
    label: 'Recall@10',
    hint: 'How often the item they actually chose was in the ten.',
  },
  {
    key: 'hit_rate_at_10' as const,
    label: 'Hit rate@10',
    hint: 'The share of sessions with at least one hit.',
  },
  {
    key: 'coverage' as const,
    label: 'Coverage',
    hint: 'How much of the catalogue it is willing to recommend.',
  },
];

export function ModelDetailRoute() {
  const { versionId = '' } = useParams();
  const query = useQuery(modelVersionQuery(versionId));

  return (
    <div className="page">
      <Breadcrumbs
        crumbs={[
          { label: 'Models', to: '/models' },
          { label: query.data ? `v${query.data.version_number}` : 'Version' },
        ]}
      />
      <QueryState query={query} label="this model version">
        {(version) => <VersionPanel version={version} />}
      </QueryState>
    </div>
  );
}

function VersionPanel({ version }: { version: ModelVersion }) {
  const [dialog, setDialog] = useState<'activate' | 'archive' | 'rollback' | null>(null);
  const { actions } = version;

  return (
    <>
      <div className="page__head">
        <h1 className="page__title">Version {version.version_number}</h1>
        <p className="page__lede">
          {version.model_type}, trained {formatDateTime(version.created_at)}.
        </p>
      </div>

      {version.status === 'failed_deployment' ? (
        <Banner kind="danger">
          {version.failure_note ??
            'This version was activated but the deployment did not come up. The previous version is still serving.'}
        </Banner>
      ) : null}
      {!version.eligible && version.status !== 'active' ? (
        <Banner kind="warning">
          {actions.activate.reason ??
            'This version did not meet the quality floor, so it cannot be activated.'}
        </Banner>
      ) : null}

      <DefinitionList
        items={[
          { term: 'Status', value: <Badge domain="model" value={version.status} /> },
          { term: 'Trained', value: formatDateTime(version.created_at) },
          { term: 'Archived', value: formatDateTime(version.archived_at) },
          { term: 'Feature contract', value: version.artifact.feature_contract },
          { term: 'Embedding dimension', value: version.artifact.embedding_dim },
          {
            term: 'Artifact digest',
            value: <code>{version.artifact.digest}</code>,
          },
        ]}
      />

      <section>
        <h2 className="eyebrow">How it compares</h2>
        <ComparisonTable version={version} />
      </section>

      <div className="action-row">
        <GatedAction
          label="Activate"
          allowed={actions.activate.allowed}
          reason={actions.activate.reason}
          variant="primary"
          onClick={() => setDialog('activate')}
        />
        <GatedAction
          label="Roll back to this"
          allowed={actions.rollback.allowed}
          reason={actions.rollback.reason}
          onClick={() => setDialog('rollback')}
        />
        <GatedAction
          label="Archive"
          allowed={actions.archive.allowed}
          reason={actions.archive.reason}
          onClick={() => setDialog('archive')}
        />
      </div>

      {dialog === 'activate' ? (
        <ActivateDialog version={version} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === 'rollback' ? (
        <RollbackDialog version={version} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === 'archive' ? (
        <ArchiveDialog version={version} onClose={() => setDialog(null)} />
      ) : null}
    </>
  );
}

function ComparisonTable({ version }: { version: ModelVersion }) {
  const active: Comparison | null = version.active_comparison;

  return (
    <table className="compare-table">
      <caption className="visually-hidden">
        This version compared with the popularity baseline and the active version
      </caption>
      <thead>
        <tr>
          <th scope="col">Measure</th>
          <th scope="col">v{version.version_number}</th>
          <th scope="col">Popularity baseline</th>
          <th scope="col">{active ? `v${active.version_number} (active)` : 'Active version'}</th>
        </tr>
      </thead>
      <tbody>
        {MEASURES.map((measure) => (
          <tr key={measure.key}>
            <th scope="row">
              {measure.label}
              <span className="compare-table__hint">{measure.hint}</span>
            </th>
            <Cell value={version.metrics[measure.key]} />
            <Cell value={version.baseline[measure.key]} />
            <Cell value={active ? active[measure.key] : null} />
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * A missing measure is an em dash and never a zero.
 *
 * `VersionMeasuresBody` makes every field nullable for this reason: a coverage
 * of 0.00 is a claim that the model recommends one item to everybody, and it
 * is the opposite of "we did not measure coverage".
 */
function Cell({ value }: { value: Measures[keyof Measures] }) {
  return <td>{value === null ? ABSENT : formatMetric(value)}</td>;
}

function ActivateDialog({ version, onClose }: { version: ModelVersion; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const mutation = useModelMutation((body: S['ActivateVersionRequest']) =>
    activateVersion(version.version_id, body),
  );
  const form = useSubmit<ModelVersion>(
    (body: S['ActivateVersionRequest']) => mutation.mutateAsync(body),
    onClose,
  );

  return (
    <Dialog
      title={`Activate version ${version.version_number}`}
      onClose={onClose}
      confirmLabel="Activate"
      busy={form.pending}
      onConfirm={() => form.submit({ reason: reason.trim() || null })}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <p className="page__lede">
        Recommendations switch to this version as soon as it comes up. If it fails to come up, the
        current version keeps serving and this one is marked failed.
      </p>
      <Textarea
        label="Reason"
        rows={3}
        value={reason}
        error={form.fieldErrors.reason}
        onChange={(event) => setReason(event.target.value)}
        hint="Optional, and kept in the audit trail."
      />
    </Dialog>
  );
}

/**
 * Roll back names the version in the body, and the server checks it.
 *
 * The dialog was opened against a page that may be minutes old. Sending
 * `target_version_id` turns "roll back to whatever is retained" into "roll
 * back to the one I was looking at", and a mismatch is refused rather than
 * quietly rolling back to something else.
 */
function RollbackDialog({ version, onClose }: { version: ModelVersion; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const mutation = useModelMutation((body: S['RollbackRequest']) =>
    rollbackModel(version.model_id, body),
  );
  const form = useSubmit<ModelVersion>(
    (body: S['RollbackRequest']) => mutation.mutateAsync(body),
    onClose,
  );

  return (
    <Dialog
      title={`Roll back to version ${version.version_number}`}
      onClose={onClose}
      confirmLabel="Roll back"
      confirmVariant="danger"
      busy={form.pending}
      confirmDisabled={reason.trim().length < 4}
      onConfirm={() =>
        form.submit({ target_version_id: version.version_id, reason: reason.trim() })
      }
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <p className="page__lede">
        The version serving now is retired and this one takes over. A reason is required — whoever
        reads this history later needs to know what went wrong.
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

function ArchiveDialog({ version, onClose }: { version: ModelVersion; onClose: () => void }) {
  const mutation = useModelMutation((body: S['ArchiveVersionRequest']) =>
    archiveVersion(version.version_id, body),
  );
  const form = useSubmit<ModelVersion>(
    (body: S['ArchiveVersionRequest']) => mutation.mutateAsync(body),
    onClose,
  );

  return (
    <Dialog
      title={`Archive version ${version.version_number}`}
      onClose={onClose}
      confirmLabel="Archive"
      busy={form.pending}
      onConfirm={() => form.submit({ reason: 'Archived from the console.' })}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <p className="page__lede">
        It leaves the list of versions you might activate. Its metrics stay, and nothing serving is
        affected.
      </p>
    </Dialog>
  );
}
