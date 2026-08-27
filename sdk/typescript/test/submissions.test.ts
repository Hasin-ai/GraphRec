import { afterEach, describe, expect, it, vi } from 'vitest';
import { SubmissionFailedError, SubmissionTimeoutError } from '../src/index.js';
import { client, scripted } from './support.js';

function submission(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    submission_id: 's-1',
    kind: 'event_batch',
    status: 'processing',
    stage: 'received',
    reference: 'b-1',
    counts: { received: 100, accepted: 0, updated: 0, skipped: 0, failed: 0 },
    errors: [],
    error_count: 0,
    failure_code: null,
    submitted_at: '2026-08-24T10:00:00Z',
    completed_at: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

/**
 * `wait` is the one place the SDK adds a loop rather than a method.
 *
 * Bulk upsert and event batches answer `202` with a submission that is
 * `processing`, so every integration writes this poll — and writes the same
 * three bugs into it: a fixed interval that hammers the API, no ceiling so a
 * stuck job spins forever, and treating a failure as an exception that discards
 * the per-item reasons which are the only actionable part of it.
 */
describe('waiting for a submission', () => {
  it('polls until the submission is terminal, backing off as it goes', async () => {
    vi.useFakeTimers();
    const { fetch, calls } = scripted([
      { body: submission({ stage: 'validating' }) },
      { body: submission({ stage: 'applying' }) },
      { body: submission({ status: 'succeeded', stage: 'completed', counts: { received: 100, accepted: 98, updated: 0, skipped: 2, failed: 0 } }) },
    ]);
    const pending = client({}, fetch).submissions.wait('s-1');
    await vi.advanceTimersByTimeAsync(10_000);

    await expect(pending).resolves.toMatchObject({ status: 'succeeded', counts: { accepted: 98 } });
    expect(calls).toHaveLength(3);
    expect(calls.every((call) => call.method === 'GET')).toBe(true);
  });

  it('throws on a failed submission and keeps the per-item reasons', async () => {
    vi.useFakeTimers();
    const { fetch } = scripted([
      {
        body: submission({
          status: 'failed',
          stage: 'failed',
          failure_code: 'product_invalid',
          error_count: 2,
          counts: { received: 100, accepted: 98, updated: 0, skipped: 0, failed: 2 },
          errors: [
            { ref: 'sku-9', reason: 'A title is required.' },
            { ref: 'sku-12', reason: 'The price is not a positive decimal.' },
          ],
        }),
      },
    ]);
    const pending = client({}, fetch).submissions.wait('s-1').catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(1_000);
    const failure = await pending;

    expect(failure).toBeInstanceOf(SubmissionFailedError);
    // The refs are what a caller fixes. An exception carrying only "it failed"
    // would have thrown away the entire answer.
    expect((failure as SubmissionFailedError).fieldErrors.map((error) => error.field)).toEqual(['sku-9', 'sku-12']);
    expect((failure as SubmissionFailedError).submission.counts.failed).toBe(2);
  });

  it('gives up with the last state attached, so the caller can resume', async () => {
    vi.useFakeTimers();
    const { fetch } = scripted([{ body: submission({ stage: 'applying' }) }]);
    const pending = client({}, fetch).submissions.wait('s-1', { timeout: 3_000 }).catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(5_000);
    const failure = await pending;

    expect(failure).toBeInstanceOf(SubmissionTimeoutError);
    // Not a bare timeout: throwing away the last observed state would mean the
    // only way to resume is to start over.
    expect((failure as SubmissionTimeoutError).submission.stage).toBe('applying');
  });

  it('reads a submission by the batch id the caller chose', async () => {
    // The reason this route matters: if the 202 never arrived, there is no
    // submission id — but the caller still has the identifier they sent.
    const { fetch, calls } = scripted([{ body: submission({ status: 'succeeded', stage: 'completed' }) }]);
    await client({}, fetch).submissions.getBatch('nightly-2026-08-24');
    expect(calls[0]!.url).toMatch(/\/v1\/events\/batches\/nightly-2026-08-24$/);
  });

  it('returns a failed submission as a value from get, not as an exception', async () => {
    // Asking how a batch went and being told "badly" is a successful call.
    const { fetch } = scripted([{ body: submission({ status: 'failed', stage: 'failed' }) }]);
    await expect(client({}, fetch).submissions.get('s-1')).resolves.toMatchObject({ status: 'failed' });
  });
});
