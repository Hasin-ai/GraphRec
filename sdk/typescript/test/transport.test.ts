import { afterEach, describe, expect, it, vi } from 'vitest';
import { QuotaExhaustedError, RateLimitedError, TimeoutError, TransportError } from '../src/index.js';
import { client, envelope, scripted } from './support.js';

const RECOMMENDATION = {
  request_id: 'r-1',
  model_version: null,
  strategy: 'fallback',
  fallback_applied: true,
  items: [],
  ordering_policy_version: 1,
  latency_ms: 3,
};

const SUBMISSION = {
  submission_id: 's-1', kind: 'event_batch', status: 'processing', stage: 'received',
  reference: 'b-1', counts: { received: 0, accepted: 0, updated: 0, skipped: 0, failed: 0 },
  errors: [], error_count: 0, failure_code: null,
  submitted_at: '2026-08-24T10:00:00Z', completed_at: null,
};

const EVENT = {
  eventId: 'e-1', customerId: 'c-1', externalProductId: 'sku-1',
  eventType: 'view' as const, occurredAt: new Date('2026-08-24T10:00:00Z'),
};

/** Full jitter with `random()` pinned to 0 is a delay of 0 — no real sleeping. */
function noJitter(): void {
  vi.spyOn(Math, 'random').mockReturnValue(0);
}

afterEach(() => {
  vi.useRealTimers();
});

/**
 * Test 4 of `docs/SDK_DESIGN.md` §10 — `retryable` is honoured, quota is not
 * retried.
 *
 * The pair is the point. Both failures are `429` and both are `class: "limit"`,
 * and an SDK that treated them alike would either give up on a rate limit that a
 * two-second wait would clear, or hammer a quota that will not reset until the
 * billing period does.
 */
describe('what gets retried', () => {
  it('retries a 503, because the server called it retryable', async () => {
    noJitter();
    const { fetch, calls } = scripted([
      { status: 503, body: envelope('unavailable', 'service_unavailable', { retryable: true }) },
      { body: RECOMMENDATION },
    ]);
    const answer = await client({ maxRetries: 2 }, fetch).recommendations.forCustomer({
      requestId: 'r-1',
      customerId: 'c-1',
    });
    expect(answer.requestId).toBe('r-1');
    expect(calls).toHaveLength(2);
  });

  it('retries a rate limit and waits exactly as long as it was told to', async () => {
    vi.useFakeTimers();
    const { fetch, calls } = scripted([
      { status: 429, body: envelope('limit', 'rate_limited', { retry_after_seconds: 41 }) },
      { body: RECOMMENDATION },
    ]);
    const pending = client({ maxRetries: 2, timeout: 120_000 }, fetch).recommendations.forCustomer({
      requestId: 'r-1',
      customerId: 'c-1',
    });

    await vi.advanceTimersByTimeAsync(40_000);
    expect(calls, 'retried before Retry-After elapsed').toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(pending).resolves.toMatchObject({ requestId: 'r-1' });
    expect(calls).toHaveLength(2);
  });

  it('does not retry an exhausted quota, not even once', async () => {
    noJitter();
    const { fetch, calls } = scripted([
      { status: 429, body: envelope('limit', 'recommendation_quota_exhausted') },
    ]);
    await expect(
      client({ maxRetries: 5 }, fetch).recommendations.forCustomer({ requestId: 'r-1', customerId: 'c-1' }),
    ).rejects.toBeInstanceOf(QuotaExhaustedError);
    // Exactly one. Waiting does not help: the allowance resets with the period.
    expect(calls).toHaveLength(1);
  });

  it('does not retry a validation failure, which will be refused identically', async () => {
    noJitter();
    const { fetch, calls } = scripted([{ status: 422, body: envelope('validation', 'invalid_request') }]);
    await expect(
      client({ maxRetries: 5 }, fetch).recommendations.forCustomer({ requestId: 'r-1', customerId: 'c-1' }),
    ).rejects.toMatchObject({ code: 'invalid_request' });
    expect(calls).toHaveLength(1);
  });

  it('does not retry a 403, because no number of attempts grants a scope', async () => {
    noJitter();
    const { fetch, calls } = scripted([{ status: 403, body: envelope('auth', 'insufficient_scope') }]);
    await expect(client({ maxRetries: 5 }, fetch).submissions.get('s-1')).rejects.toMatchObject({
      code: 'insufficient_scope',
    });
    expect(calls).toHaveLength(1);
  });

  it('retries a connection failure and names TLS when it finally gives up', async () => {
    noJitter();
    const { fetch, calls } = scripted([{ throws: new TypeError('fetch failed') }]);
    const failure = await client({ maxRetries: 2 }, fetch)
      .recommendations.forCustomer({ requestId: 'r-1', customerId: 'c-1' })
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(TransportError);
    // "fetch failed" is not a diagnosis. Both edges pin TLS 1.3.
    expect((failure as Error).message).toMatch(/TLS 1\.3/);
    expect((failure as TransportError).reference).toBeNull();
    expect(calls).toHaveLength(3);
  });

  it('stops at maxRetries', async () => {
    noJitter();
    const { fetch, calls } = scripted([{ status: 503, body: envelope('unavailable', 'service_unavailable', { retryable: true }) }]);
    await expect(
      client({ maxRetries: 3 }, fetch).recommendations.forCustomer({ requestId: 'r-1', customerId: 'c-1' }),
    ).rejects.toMatchObject({ code: 'service_unavailable' });
    expect(calls).toHaveLength(4);
  });
});

/**
 * Test 5 of `docs/SDK_DESIGN.md` §10 — a retry sends the same identifier.
 *
 * This is the test that would have caught the convenience the design rejected:
 * generating `batch_id` inside the SDK. It would have looked like an
 * improvement, and it would have turned every retry into a second submission of
 * the same five thousand events under a key the server had never seen.
 */
describe('a retry is a retry, not a second submission', () => {
  it('resends the identical batch_id', async () => {
    noJitter();
    const { fetch, calls } = scripted([
      { status: 503, body: envelope('unavailable', 'service_unavailable', { retryable: true }) },
      { status: 202, body: SUBMISSION },
    ]);
    await client({ maxRetries: 2 }, fetch).events.submitBatch({ batchId: 'nightly-2026-08-24', events: [EVENT] });

    expect(calls).toHaveLength(2);
    const ids = calls.map((call) => (call.body as { batch_id: string }).batch_id);
    expect(ids).toEqual(['nightly-2026-08-24', 'nightly-2026-08-24']);
  });

  it('resends the identical sync_id and the identical products', async () => {
    noJitter();
    const { fetch, calls } = scripted([
      { throws: new TypeError('fetch failed') },
      { status: 202, body: { ...SUBMISSION, kind: 'product_sync', reference: 'sync-1' } },
    ]);
    await client({ maxRetries: 2 }, fetch).catalog.sync({
      syncId: 'sync-1',
      products: [{ externalId: 'sku-1', title: 'Example' }],
    });
    expect(calls).toHaveLength(2);
    expect(calls[0]!.body).toEqual(calls[1]!.body);
  });

  it('resends the identical request_id, which is what feedback will refer to', async () => {
    noJitter();
    const { fetch, calls } = scripted([
      { status: 503, body: envelope('unavailable', 'service_unavailable', { retryable: true }) },
      { body: RECOMMENDATION },
    ]);
    await client({ maxRetries: 2 }, fetch).recommendations.forCustomer({ requestId: 'r-1', customerId: 'c-1' });
    expect(calls.map((call) => (call.body as { request_id: string }).request_id)).toEqual(['r-1', 'r-1']);
  });
});

describe('the budget is a deadline, not an attempt count', () => {
  it('gives up when the next wait would not fit, rather than overrunning', async () => {
    vi.useFakeTimers();
    const { fetch, calls } = scripted([
      { status: 429, body: envelope('limit', 'rate_limited', { retry_after_seconds: 60 }) },
    ]);
    const pending = client({ maxRetries: 5, timeout: 1_000 }, fetch)
      .recommendations.forCustomer({ requestId: 'r-1', customerId: 'c-1' })
      .catch((error: unknown) => error);

    await vi.advanceTimersByTimeAsync(1_000);
    // A minute of backoff does not fit in a one-second budget, so the caller
    // gets the rate limit itself rather than a hot path blocked for a minute.
    expect(await pending).toBeInstanceOf(RateLimitedError);
    expect(calls).toHaveLength(1);
  });

  it('reports a timeout when the server simply never answers', async () => {
    const slow = (async (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal!.reason as Error), { once: true });
      })) as typeof globalThis.fetch;

    await expect(
      client({ timeout: 20 }, slow).recommendations.forCustomer({ requestId: 'r-1', customerId: 'c-1' }),
    ).rejects.toBeInstanceOf(TimeoutError);
  });

  it('propagates the caller’s own cancellation untouched', async () => {
    const controller = new AbortController();
    const hanging = (async (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal!.reason as Error), { once: true });
      })) as typeof globalThis.fetch;

    const pending = client({ timeout: 5_000 }, hanging).recommendations.forCustomer(
      { requestId: 'r-1', customerId: 'c-1' },
      { signal: controller.signal },
    );
    controller.abort();
    // Not wrapped: an abort the caller asked for is not a GraphRec failure, and
    // dressing it up as one would break every `if (error.name === 'AbortError')`.
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('correlation', () => {
  it('sends a caller-supplied trace id as X-Request-Id', async () => {
    const { fetch, calls } = scripted([{ body: RECOMMENDATION }]);
    await client({}, fetch).recommendations.forCustomer(
      { requestId: 'r-1', customerId: 'c-1' },
      { requestId: 'trace-abc' },
    );
    expect(calls[0]!.headers['X-Request-Id']).toBe('trace-abc');
  });

  it('identifies itself, so an estate can find one caller in its logs', async () => {
    const { fetch, calls } = scripted([{ body: RECOMMENDATION }]);
    await client({ userAgent: 'acme-storefront/3.2' }, fetch).recommendations.forCustomer({
      requestId: 'r-1',
      customerId: 'c-1',
    });
    expect(calls[0]!.headers['User-Agent']).toMatch(/^graphrec-node\/\S+ acme-storefront\/3\.2$/);
  });
});
