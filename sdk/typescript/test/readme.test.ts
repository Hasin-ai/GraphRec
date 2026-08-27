/**
 * Design test 7: the examples in the README execute.
 *
 * Two halves, and both are needed. The first asserts that every fenced block in
 * `README.md` is character-for-character a region of `test/examples.ts`, which
 * the compiler has already typechecked against the shipped surface — so a block
 * that names a field the SDK dropped fails `tsc`, not a customer. The second
 * runs those regions against a recorded transport, so a block that compiles but
 * calls the wrong route, or reads a response field the server does not send,
 * fails here.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import type { MockInstance } from 'vitest';

import { QuotaExhaustedError } from '../src/index.js';

import * as examples from './examples.js';
import { KEY, TENANT, TENANT_HEX, envelope, scripted } from './support.js';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const README = readFileSync(new URL('../README.md', import.meta.url), 'utf8');
const EXAMPLES = readFileSync(`${HERE}examples.ts`, 'utf8');

/** `// #region name` … `// #endregion name`, dedented by the common indent. */
function regions(source: string): Map<string, string> {
  const found = new Map<string, string>();
  const pattern = /\/\/ #region (\S+)\n([\s\S]*?)\n[^\S\n]*\/\/ #endregion \1/g;
  for (const match of source.matchAll(pattern)) {
    const body = match[2] ?? '';
    const indents = body
      .split('\n')
      .filter((line) => line.trim() !== '')
      .map((line) => line.length - line.trimStart().length);
    const common = Math.min(...indents);
    found.set(
      match[1] ?? '',
      body
        .split('\n')
        .map((line) => line.slice(common))
        .join('\n')
        .trimEnd(),
    );
  }
  return found;
}

/** `<!-- example: name -->` followed by the next fenced `ts` block. */
function blocks(markdown: string): Map<string, string> {
  const found = new Map<string, string>();
  const pattern = /<!-- example: (\S+) -->\n```ts\n([\s\S]*?)\n```/g;
  for (const match of markdown.matchAll(pattern)) {
    found.set(match[1] ?? '', match[2] ?? '');
  }
  return found;
}

/**
 * The response schemas, so the fixtures below cannot drift from the API.
 *
 * Only `required` is checked, and only for presence. A full JSON Schema
 * validator would be better and is a dependency this package does not have; the
 * failure this catches is the one that actually happens — a fixture invented
 * from memory that omits a field the decoder reads, which makes an example look
 * green while the real response would have thrown.
 */
interface Schema {
  required?: string[];
  properties?: Record<string, Schema>;
  items?: Schema;
  $ref?: string;
  anyOf?: Schema[];
}

const OPENAPI = JSON.parse(
  readFileSync(new URL('../../../frontend/openapi.json', import.meta.url), 'utf8'),
) as {
  paths: Record<string, Record<string, { responses: Record<string, { content?: Record<string, { schema?: Schema }> }> }>>;
  components: { schemas: Record<string, Schema> };
};

function deref(schema: Schema | undefined): Schema | undefined {
  if (!schema) return undefined;
  if (schema.$ref) return deref(OPENAPI.components.schemas[schema.$ref.split('/').pop()!]);
  return schema;
}

function responseSchema(method: string, path: string): Schema {
  const operation = OPENAPI.paths[path]?.[method.toLowerCase()];
  if (!operation) throw new Error(`no such operation: ${method} ${path}`);
  const success = Object.entries(operation.responses).find(([code]) => code.startsWith('2'));
  const schema = deref(success?.[1].content?.['application/json']?.schema);
  if (!schema) throw new Error(`no success schema: ${method} ${path}`);
  return schema;
}

function conforms(schema: Schema | undefined, value: unknown, where: string): void {
  const resolved = deref(schema);
  if (!resolved || value === null || value === undefined) return;
  if (Array.isArray(value)) {
    value.forEach((entry, index) => conforms(resolved.items, entry, `${where}[${index}]`));
    return;
  }
  if (typeof value !== 'object') return;
  const record = value as Record<string, unknown>;
  for (const field of resolved.required ?? []) {
    expect(Object.hasOwn(record, field), `${where}.${field} is missing`).toBe(true);
  }
  for (const [field, child] of Object.entries(resolved.properties ?? {})) {
    if (Object.hasOwn(record, field)) {
      const branch = child.anyOf?.find((option) => option.$ref) ?? child;
      conforms(branch, record[field], `${where}.${field}`);
    }
  }
}

const REGIONS = regions(EXAMPLES);
const BLOCKS = blocks(README);

describe('the README', () => {
  it('has annotated code blocks at all', () => {
    // A floor, so that a change to the marker syntax cannot make every
    // assertion below pass over an empty map.
    expect(BLOCKS.size).toBeGreaterThanOrEqual(7);
  });

  it('names a region for every block it annotates', () => {
    expect([...BLOCKS.keys()].sort()).toEqual([...REGIONS.keys()].sort());
  });

  it.each([...BLOCKS.keys()])('block %s is exactly the compiled region', (name) => {
    expect(BLOCKS.get(name)).toBe(REGIONS.get(name));
  });

  it('has no fenced ts block that escapes the check', () => {
    // Every `ts` fence must be annotated. An un-annotated one is a snippet
    // nothing compiles, which is the thing this test exists to prevent.
    const fences = [...README.matchAll(/```ts\n/g)].length;
    expect(fences).toBe(BLOCKS.size);
  });
});

describe('the examples', () => {
  // The fixtures are the wire, not an approximation of it. `conforms()` below
  // checks each one against the response schema in `frontend/openapi.json`,
  // because an example that decodes a field the server does not send is exactly
  // the defect this suite exists to catch, and a hand-written fixture agreeing
  // with a hand-written decoder catches nothing.
  const RECOMMENDATION = {
    request_id: 'req-1',
    model_version: { version_id: 'mv-1', version_number: 7 },
    strategy: 'personalized',
    fallback_applied: false,
    items: [
      { external_product_id: 'sku-1', rank: 1, score: 0.91, candidate_source: 'co_view' },
    ],
    ordering_policy_version: 2,
    latency_ms: 41,
  };
  const FEEDBACK = {
    request_id: 'req-1',
    received: 1,
    accepted: 1,
    duplicates: 0,
    unknown_products: [],
  };
  const RECEIPT = {
    event_id: '11111111-1111-4111-8111-111111111111',
    status: 'duplicate_confirmed',
    first_received_at: '2026-08-24T09:00:00Z',
  };
  const COUNTS = { received: 1, accepted: 1, updated: 0, skipped: 0, failed: 0 };
  const submission = (over: Record<string, unknown> = {}) => ({
    submission_id: 'sub-1',
    kind: 'product_sync',
    status: 'processing',
    stage: 'received',
    reference: '2026-08-24-nightly',
    counts: { received: 1, accepted: 0, updated: 0, skipped: 0, failed: 0 },
    errors: [],
    error_count: 0,
    failure_code: null,
    submitted_at: '2026-08-24T10:00:00Z',
    completed_at: null,
    ...over,
  });
  const ACCEPTED = submission();
  const SUCCEEDED = submission({
    status: 'succeeded',
    stage: 'completed',
    counts: COUNTS,
    completed_at: '2026-08-24T10:00:30Z',
  });
  const FAILED = submission({
    status: 'failed',
    stage: 'failed',
    counts: { received: 1, accepted: 0, updated: 0, skipped: 0, failed: 1 },
    errors: [{ ref: 'sku-1', reason: 'Title is required.' }],
    error_count: 1,
    failure_code: 'items_rejected',
    completed_at: '2026-08-24T10:00:30Z',
  });

  // Re-installed per test rather than once for the block: `restoreMocks` in
  // `vitest.config.ts` puts the real `console.log` back between tests, which is
  // the setting that keeps every other suite honest.
  let log: MockInstance<typeof console.log>;

  beforeEach(() => {
    process.env.GRAPHREC_API_KEY = KEY;
    process.env.GRAPHREC_TENANT_ID = TENANT;
    log = vi.spyOn(console, 'log').mockImplementation(() => undefined);
  });

  afterEach(() => {
    delete process.env.GRAPHREC_API_KEY;
    delete process.env.GRAPHREC_TENANT_ID;
  });

  /** Stub the global, so `construct()` runs the README's own constructor call. */
  function record(replies: Parameters<typeof scripted>[0]) {
    const { fetch, calls } = scripted(replies);
    vi.stubGlobal('fetch', fetch);
    return calls;
  }

  it('constructs against the two hosts the README claims', () => {
    record([{ status: 200, body: RECOMMENDATION }]);
    const hosts = examples.construct().hosts;
    expect(hosts.control).toBe('https://api.graphrec.example');
    expect(hosts.data).toBe(`https://${TENANT_HEX}.serve.graphrec.example`);
  });

  it('asks for and prints recommendations', async () => {
    const calls = record([{ status: 200, body: RECOMMENDATION }]);
    const answer = await examples.recommend(examples.construct());

    expect(calls[0]?.url).toBe(
      `https://${TENANT_HEX}.serve.graphrec.example/v1/recommendations`,
    );
    expect(answer.items[0]?.externalProductId).toBe('sku-1');
    expect(log).toHaveBeenCalledWith(1, 'sku-1', 0.91);
  });

  it('reports impressions and conversions for that answer', async () => {
    const calls = record([
      { status: 200, body: RECOMMENDATION },
      { status: 200, body: FEEDBACK },
    ]);
    const gr = examples.construct();
    await examples.report(gr, await examples.recommend(gr));

    expect(calls.map((call) => new URL(call.url).pathname)).toEqual([
      '/v1/recommendations',
      '/v1/feedback/impressions',
      '/v1/feedback/conversions',
    ]);
    const conversion = calls[2]?.body as {
      request_id: string;
      events: { event_id: string; value: number }[];
    };
    expect(conversion.request_id).toBe('req-1');
    expect(conversion.events[0]).toMatchObject({ event_id: 'order-4471', value: 19.99 });
  });

  it('syncs a catalogue and waits for the submission', async () => {
    const calls = record([
      { status: 202, body: ACCEPTED },
      { status: 200, body: SUCCEEDED },
    ]);
    vi.useFakeTimers();
    const pending = examples.sync(examples.construct());
    await vi.advanceTimersByTimeAsync(1_000);
    const finished = await pending;
    vi.useRealTimers();

    expect(new URL(calls[0]!.url).pathname).toBe('/v1/products:bulk-upsert');
    expect(calls[1]?.url).toBe('https://api.graphrec.example/v1/submissions/sub-1');
    expect(finished.counts).toEqual({
      received: 1,
      accepted: 1,
      updated: 0,
      skipped: 0,
      failed: 0,
    });
    expect(log).toHaveBeenCalledWith(finished.counts);
  });

  it('submits an event and reads the duplicate branch', async () => {
    const calls = record([{ status: 200, body: RECEIPT }]);
    await examples.ingest(examples.construct());

    expect(calls[0]?.url).toBe('https://api.graphrec.example/v1/events');
    expect(log).toHaveBeenCalledWith('already had it, first seen at', '2026-08-24T09:00:00Z');
  });

  it('separates a spent quota from a rate limit', async () => {
    record([
      { status: 429, body: envelope('limit', 'recommendation_quota_exhausted') },
    ]);
    await expect(examples.handle(examples.construct())).resolves.toBe('quota');

    record([
      {
        status: 429,
        body: envelope('limit', 'rate_limited', { retry_after_seconds: 30 }),
      },
    ]);
    await expect(examples.handle(examples.construct())).resolves.toBe('rate-limited');
  });

  it('reads the per-item errors off a failed submission', async () => {
    record([{ status: 200, body: FAILED }]);
    await expect(examples.failed(examples.construct())).resolves.toEqual([
      'sku-1: Title is required.',
    ]);
  });

  it.each([
    ['POST', '/v1/recommendations', () => RECOMMENDATION],
    ['POST', '/v1/feedback/impressions', () => FEEDBACK],
    ['POST', '/v1/events', () => RECEIPT],
    ['POST', '/v1/products:bulk-upsert', () => ACCEPTED],
    ['GET', '/v1/submissions/{submission_id}', () => SUCCEEDED],
    ['GET', '/v1/submissions/{submission_id}', () => FAILED],
  ])('answers %s %s with a fixture the schema would accept', (method, path, fixture) => {
    conforms(responseSchema(method, path), fixture(), path);
  });

  it('still refuses a quota refusal a second attempt, in the README path', async () => {
    // The README promises "attempted exactly once". The claim is checked in
    // `transport.test.ts` at the transport; here it is checked through the
    // example a reader would copy, with the default `maxRetries` of 2.
    const calls = record([
      { status: 429, body: envelope('limit', 'recommendation_quota_exhausted') },
    ]);
    await examples.handle(examples.construct()).catch((error: unknown) => {
      expect(error).toBeInstanceOf(QuotaExhaustedError);
    });
    expect(calls).toHaveLength(1);
  });
});
