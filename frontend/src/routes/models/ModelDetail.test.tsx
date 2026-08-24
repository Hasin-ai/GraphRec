/**
 * The three-way comparison, and the three gate-5 controls beside it.
 *
 * Two rules are asserted here because both are easy to break by being
 * helpful: a measure the platform did not record renders as an em dash and
 * never as a zero, and a control's enabled state comes from `actions.*`
 * rather than from reading `status` and deciding.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import { ModelDetailRoute } from './ModelDetail';
import { ADMIN_ME, DEVELOPER_ME, renderGuarded, respondWith } from '../../test/tenant';
import { resetSessionsForTest } from '../../api/session';

const VERSION_ID = '00000000-0000-4000-8000-0000000000a1';

const VERSION = {
  version_id: VERSION_ID,
  model_id: '00000000-0000-4000-8000-0000000000b1',
  training_job_id: '00000000-0000-4000-8000-0000000000c1',
  version_number: 8,
  model_type: 'DGSR',
  status: 'eligible',
  eligible: true,
  created_at: '2026-08-01T00:00:00Z',
  archived_at: null,
  failure_note: null,
  metrics: { ndcg_at_10: 0.412, recall_at_10: 0.531, hit_rate_at_10: 0.62, coverage: null },
  baseline: { ndcg_at_10: 0.201, recall_at_10: 0.318, hit_rate_at_10: 0.4, coverage: 0.11 },
  active_comparison: {
    version_number: 7,
    ndcg_at_10: 0.39,
    recall_at_10: 0.51,
    hit_rate_at_10: 0.6,
    coverage: 0.22,
  },
  artifact: {
    uri: 's3://artifacts/8',
    digest: 'sha256:abcd',
    embedding_dim: 128,
    feature_contract: 'v2',
    snapshot_id: '00000000-0000-4000-8000-0000000000d1',
  },
  actions: {
    activate: { allowed: true, reason: null },
    rollback: { allowed: false, reason: 'This version is not the retained rollback target.' },
    archive: { allowed: true, reason: null },
  },
};

function render(body: unknown = VERSION, me = ADMIN_ME) {
  respondWith({ '/v1/me': me, '/v1/model-versions/': body });
  return renderGuarded(
    '/models/:versionId',
    <ModelDetailRoute />,
    ['tenant_administrator'],
    `/models/${VERSION_ID}`,
  );
}

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
});

describe('/models/:versionId', () => {
  it('refuses a Tenant Developer at the route', async () => {
    render(VERSION, DEVELOPER_ME);
    expect(await screen.findByRole('heading', { name: /do not have access/i })).toBeVisible();
  });

  it('puts this version, the baseline and the active one side by side', async () => {
    render();

    const table = await screen.findByRole('table', { name: /compared with/i });
    const headers = within(table)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    expect(headers).toEqual(['Measure', 'v8', 'Popularity baseline', 'v7 (active)']);

    const ndcg = within(table).getByRole('row', { name: /nDCG@10/ });
    expect(within(ndcg).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      '0.412',
      '0.201',
      '0.390',
    ]);
  });

  it('renders an unmeasured coverage as an em dash, not a zero', async () => {
    render();

    const table = await screen.findByRole('table', { name: /compared with/i });
    const coverage = within(table).getByRole('row', { name: /Coverage/ });
    const cells = within(coverage).getAllByRole('cell').map((cell) => cell.textContent);
    expect(cells[0]).toBe('—');
    expect(cells[0]).not.toBe('0.000');
  });

  it('disables roll back with the server’s sentence, and leaves activate alone', async () => {
    render();

    const rollback = await screen.findByRole('button', { name: 'Roll back to this' });
    expect(rollback).toBeDisabled();
    expect(
      document.getElementById(rollback.getAttribute('aria-describedby')!),
    ).toHaveTextContent('This version is not the retained rollback target.');

    expect(screen.getByRole('button', { name: 'Activate' })).toBeEnabled();
  });

  it('shows no active column when nothing is active', async () => {
    render({ ...VERSION, active_comparison: null });

    const table = await screen.findByRole('table', { name: /compared with/i });
    const headers = within(table)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    expect(headers[3]).toBe('Active version');
    const ndcg = within(table).getByRole('row', { name: /nDCG@10/ });
    expect(within(ndcg).getAllByRole('cell')[2]).toHaveTextContent('—');
  });
});
