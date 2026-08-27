import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  AuthenticationError,
  ConflictError,
  GraphRecError,
  InternalError,
  NotFoundError,
  PermissionError,
  QuotaExhaustedError,
  RateLimitedError,
  UnavailableError,
  ValidationError,
} from '../src/index.js';
import { errorFrom } from '../src/errors.js';
import { client, envelope, scripted } from './support.js';

const repo = fileURLToPath(new URL('../../../', import.meta.url));
const serverErrors = readFileSync(`${repo}graphrec/common/errors.py`, 'utf8');

/**
 * Test 3 of `docs/SDK_DESIGN.md` §10 — the error mapping is total.
 *
 * Driven from `graphrec/common/errors.py` rather than from a list written here,
 * so the day somebody adds an eighth `ErrorClass` this fails instead of quietly
 * routing it to the base class. A client that silently degrades a new failure
 * into "some error" is how a retry loop ends up retrying something it should not.
 */
describe('every class the server can emit has an exception', () => {
  const classes = [...serverErrors.matchAll(/^\s{4}([A-Z_]+) = "([a-z_]+)"$/gm)]
    .filter((match) => ['VALIDATION', 'CONFLICT', 'LIMIT', 'UNAVAILABLE', 'AUTH', 'NOT_FOUND', 'INTERNAL'].includes(match[1]!))
    .map((match) => match[2]!);

  const defaults = Object.fromEntries(
    [...serverErrors.matchAll(/ErrorClass\.([A-Z_]+): (\d+),/g)].map((match) => [match[1]!, Number(match[2])]),
  );

  it('found the seven classes and their default statuses in the server source', () => {
    // A floor. Without it, a regex that matched nothing would make every
    // assertion below pass over an empty list.
    expect(classes).toHaveLength(7);
    expect(Object.keys(defaults)).toHaveLength(7);
  });

  it.each(classes)('maps class %s to a specific subclass', (cls) => {
    const status = defaults[cls.toUpperCase()]!;
    const error = errorFrom(status, envelope(cls, `${cls}_code`), 'rid');
    expect(error).toBeInstanceOf(GraphRecError);
    expect(error.constructor).not.toBe(GraphRecError);
    expect(error.errorClass).toBe(cls);
    expect(error.status).toBe(status);
  });
});

describe('the status decides where class alone cannot', () => {
  it('separates 401 from 403, which the server reports as the same class', () => {
    // `ForbiddenError` sets `error_class = ErrorClass.AUTH` with
    // `status_code = 403`. Switching on the class alone cannot tell "we do not
    // know who you are" from "we know, and no" — two failures with completely
    // different remedies.
    expect(errorFrom(401, envelope('auth', 'unauthenticated'), null)).toBeInstanceOf(AuthenticationError);
    expect(errorFrom(403, envelope('auth', 'insufficient_scope'), null)).toBeInstanceOf(PermissionError);
    expect(errorFrom(403, envelope('auth', 'tenant_not_active'), null)).toBeInstanceOf(PermissionError);
  });

  it('splits 429 into the one that waiting fixes and the one it does not', () => {
    const limited = errorFrom(429, envelope('limit', 'rate_limited', { retry_after_seconds: 41 }), null);
    const quota = errorFrom(429, envelope('limit', 'recommendation_quota_exhausted'), null);

    expect(limited).toBeInstanceOf(RateLimitedError);
    expect(quota).toBeInstanceOf(QuotaExhaustedError);
    expect(limited.isTransient).toBe(true);
    expect(quota.isTransient).toBe(false);
  });

  it('keeps 413 in the validation family, where the server puts it', () => {
    expect(errorFrom(413, envelope('validation', 'request_too_large'), null)).toBeInstanceOf(ValidationError);
  });

  it.each([
    [409, 'conflict', 'product_already_exists', ConflictError],
    [404, 'not_found', 'not_found', NotFoundError],
    [503, 'unavailable', 'model_not_ready', UnavailableError],
    [500, 'internal', 'internal_error', InternalError],
  ])('maps %i to the right class', (status, cls, code, expected) => {
    expect(errorFrom(status, envelope(cls, code), null)).toBeInstanceOf(expected as never);
  });
});

describe('the envelope survives intact', () => {
  it('keeps the reference, the field errors and the retry hint', async () => {
    const { fetch } = scripted([
      {
        status: 422,
        body: envelope('validation', 'product_invalid', {
          field_errors: [{ field: 'products[0].title', reason: 'is required' }],
        }),
      },
    ]);
    await expect(
      client({}, fetch).catalog.sync({ syncId: 's', products: [{ externalId: 'p', title: 'T' }] }),
    ).rejects.toMatchObject({
      code: 'product_invalid',
      reference: 'ref-0001',
      fieldErrors: [{ field: 'products[0].title', reason: 'is required' }],
    });
  });

  it('names the offending fields in the message, because that is what a trace shows', async () => {
    const { fetch } = scripted([
      {
        status: 422,
        body: envelope('validation', 'product_invalid', {
          reason: 'One or more products were rejected.',
          field_errors: [
            { field: 'products[0].title', reason: 'is required' },
            { field: 'products[1].price', reason: 'must be a decimal string' },
            { field: 'products[2].external_id', reason: 'is too long' },
            { field: 'products[3].category', reason: 'is too long' },
          ],
        }),
      },
    ]);
    const failure = (await client({}, fetch)
      .catalog.sync({ syncId: 's', products: [{ externalId: 'p', title: 'T' }] })
      .catch((error: unknown) => error)) as Error;

    // Three, then a count. A message is not a report — the full list is on the
    // error — but 'product_invalid' alone sends the reader back to the API to
    // find out what they already had.
    expect(failure.message).toContain('products[0].title: is required');
    expect(failure.message).toContain('and 1 more');
    expect(failure.message).not.toContain('products[3]');
  });

  it('falls back to X-Request-Id when a failure never reached the application', async () => {
    // A 502 from a proxy is HTML, not an envelope. Losing the status and the
    // request id there would leave the caller with nothing traceable at all.
    const { fetch } = scripted([{ status: 502, body: undefined, headers: { 'X-Request-Id': 'edge-9' } }]);
    await expect(
      client({}, fetch).recommendations.forCustomer({ requestId: 'r', customerId: 'c' }),
    ).rejects.toMatchObject({ status: 502, reference: 'edge-9', errorClass: 'unavailable' });
  });
});

describe('bounds are checked before a request is built', () => {
  it('rejects a naive timestamp locally, with the same error type the server uses', async () => {
    // `parse_timestamp` refuses a naive instant rather than assuming UTC. Caught
    // here it is one exception; caught there it is a per-item rejection inside a
    // submission, minutes after the batch was accepted.
    const { fetch, calls } = scripted([{ body: {} }]);
    await expect(
      client({}, fetch).events.submit({
        eventId: 'e', customerId: 'c', externalProductId: 'p',
        eventType: 'view', occurredAt: '2026-08-14T09:41:00',
      }),
    ).rejects.toBeInstanceOf(ValidationError);
    expect(calls).toHaveLength(0);
  });

  it('rejects a top_n above the published maximum without a round trip', async () => {
    const { fetch, calls } = scripted([{ body: {} }]);
    await expect(
      client({}, fetch).recommendations.forCustomer({ requestId: 'r', customerId: 'c', topN: 500 }),
    ).rejects.toMatchObject({ fieldErrors: [{ field: 'top_n', reason: expect.stringContaining('100') }] });
    expect(calls).toHaveLength(0);
  });
});
