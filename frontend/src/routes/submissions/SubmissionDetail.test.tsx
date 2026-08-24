/**
 * Live polling, and — the part that actually matters — when it stops.
 *
 * §10.8 sets two seconds for a submission and a terminal status as the stop
 * condition. The stop is the interesting half: a page that keeps asking about
 * a finished submission costs a request every two seconds for as long as the
 * tab stays open, and the tab that stays open is exactly the one somebody left
 * on a second monitor.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { SubmissionDetailRoute } from './SubmissionDetail';
import { DEVELOPER_ME, renderGuarded, respondWith } from '../../test/tenant';
import { resetSessionsForTest } from '../../api/session';

const SUBMISSION_ID = '00000000-0000-4000-8000-0000000000e1';

const PROCESSING = {
  submission_id: SUBMISSION_ID,
  reference: 'sync-2026-08-24',
  kind: 'product_sync',
  status: 'processing',
  stage: 'applying',
  submitted_at: '2026-08-24T10:00:00Z',
  completed_at: null,
  failure_code: null,
  counts: { received: 100, accepted: 0, updated: 0, skipped: 0, failed: 0 },
  error_count: 0,
  errors: [],
};

const SUCCEEDED = {
  ...PROCESSING,
  status: 'succeeded',
  stage: 'completed',
  completed_at: '2026-08-24T10:00:20Z',
  counts: { received: 100, accepted: 98, updated: 0, skipped: 0, failed: 2 },
  error_count: 2,
  errors: [
    { ref: 'sku-9', reason: 'Price is not a number.' },
    { ref: 'sku-12', reason: 'Unknown availability.' },
  ],
};

function countSubmissionCalls(): number {
  return vi
    .mocked(globalThis.fetch)
    .mock.calls.filter(([url]) => String(url).includes('/v1/submissions/')).length;
}

function render() {
  return renderGuarded(
    '/submissions/:submissionId',
    <SubmissionDetailRoute />,
    ['tenant_developer'],
    `/submissions/${SUBMISSION_ID}`,
  );
}

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('/submissions/:submissionId', () => {
  it('polls every two seconds while the submission is processing', async () => {
    respondWith({ '/v1/me': DEVELOPER_ME, '/v1/submissions/': PROCESSING });
    render();

    await screen.findByText(/sync-2026-08-24/);
    const first = countSubmissionCalls();

    await vi.advanceTimersByTimeAsync(2100);
    await waitFor(() => expect(countSubmissionCalls()).toBeGreaterThan(first));
  });

  it('stops once the submission is terminal', async () => {
    respondWith({ '/v1/me': DEVELOPER_ME, '/v1/submissions/': SUCCEEDED });
    render();

    await screen.findByText(/sync-2026-08-24/);
    const settled = countSubmissionCalls();

    await vi.advanceTimersByTimeAsync(10_000);
    expect(countSubmissionCalls()).toBe(settled);
  });

  it('lists what was rejected, and says the rest was applied', async () => {
    respondWith({ '/v1/me': DEVELOPER_ME, '/v1/submissions/': SUCCEEDED });
    render();

    expect(await screen.findByText('Price is not a number.')).toBeVisible();
    expect(screen.getByText(/Everything else in the batch was applied/)).toBeVisible();
  });
});
