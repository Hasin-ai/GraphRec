import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { KEY, TENANT, TENANT_HEX, client, scripted } from './support.js';

/**
 * Test 1 of `docs/SDK_DESIGN.md` §10 — the route table matches the schema.
 *
 * Both directions, because only one of them is the interesting one. Checking
 * that every SDK method hits a real path catches a typo, which TypeScript nearly
 * catches anyway. Checking that every *public* route has a method catches the
 * drift that actually happens: the API grows a route, nobody tells the SDK, and
 * the gap is found by a customer reading `openapi.json` and asking why the
 * library cannot do the thing the documentation says the API does.
 *
 * The data-plane direction is automatic — an operation whose `servers[0]` names
 * the per-tenant host is by construction something a credential calls, so the
 * rule needs no list to maintain. The control plane has sixty-odd console routes
 * that are emphatically not the SDK's, so its four are named, with the reason.
 */

const repo = fileURLToPath(new URL('../../../', import.meta.url));
const schema = JSON.parse(readFileSync(`${repo}frontend/openapi.json`, 'utf8')) as {
  paths: Record<string, Record<string, { servers?: { url: string }[] }>>;
};

type Host = 'control' | 'data';

function hostOf(path: string, method: string): Host | null {
  const operation = schema.paths[path]?.[method.toLowerCase()];
  if (!operation) return null;
  const url = operation.servers?.[0]?.url ?? '';
  return url.includes('{tenant}') ? 'data' : 'control';
}

/** Every route the SDK is expected to reach, and the host that must answer it. */
const EXPECTED: { method: string; path: string; host: Host }[] = [
  { method: 'POST', path: '/v1/products:bulk-upsert', host: 'control' },
  { method: 'POST', path: '/v1/events', host: 'control' },
  { method: 'POST', path: '/v1/events/batches', host: 'control' },
  { method: 'GET', path: '/v1/events/batches/{batch_id}', host: 'control' },
  { method: 'GET', path: '/v1/submissions/{submission_id}', host: 'control' },
  { method: 'POST', path: '/v1/recommendations', host: 'data' },
  { method: 'POST', path: '/v1/recommendations/session', host: 'data' },
  { method: 'POST', path: '/v1/feedback/impressions', host: 'data' },
  { method: 'POST', path: '/v1/feedback/clicks', host: 'data' },
  { method: 'POST', path: '/v1/feedback/conversions', host: 'data' },
];

const CONTROL = 'https://api.graphrec.example';
const DATA = `https://${TENANT_HEX}.serve.graphrec.example`;

/** Drive every method once and record where it went. */
async function exercise(): Promise<{ method: string; path: string; host: Host }[]> {
  const submission = {
    submission_id: 's-1',
    kind: 'event_batch',
    status: 'succeeded',
    stage: 'completed',
    reference: 'b-1',
    counts: { received: 1, accepted: 1, updated: 0, skipped: 0, failed: 0 },
    errors: [],
    error_count: 0,
    failure_code: null,
    submitted_at: '2026-08-24T10:00:00Z',
    completed_at: '2026-08-24T10:00:01Z',
  };
  const recommendation = {
    request_id: 'r-1',
    model_version: null,
    strategy: 'fallback',
    fallback_applied: true,
    items: [],
    ordering_policy_version: 1,
    latency_ms: 4,
  };
  const feedback = {
    request_id: 'r-1',
    received: 1,
    accepted: 1,
    duplicates: 0,
    unknown_products: [],
  };

  const { fetch, calls } = scripted([
    { body: submission },
    { body: { event_id: 'e-1', status: 'accepted', first_received_at: null } },
    { body: submission },
    { body: submission },
    { body: submission },
    { body: recommendation },
    { body: recommendation },
    { body: feedback },
    { body: feedback },
    { body: feedback },
  ]);
  const gr = client({}, fetch);

  const occurredAt = new Date('2026-08-24T10:00:00Z');
  const event = {
    eventId: 'e-1',
    customerId: 'c-1',
    externalProductId: 'sku-1',
    eventType: 'view' as const,
    occurredAt,
  };
  const events = [{ eventId: 'e-1', externalProductId: 'sku-1' }];

  await gr.catalog.sync({ syncId: 's-1', products: [{ externalId: 'sku-1', title: 'A' }] });
  await gr.events.submit(event);
  await gr.events.submitBatch({ batchId: 'b-1', events: [event] });
  await gr.submissions.getBatch('b-1');
  await gr.submissions.get('s-1');
  await gr.recommendations.forCustomer({ requestId: 'r-1', customerId: 'c-1' });
  await gr.recommendations.forSession({ requestId: 'r-1', sessionId: 'sess-1' });
  await gr.feedback.impressions({ requestId: 'r-1', events });
  await gr.feedback.clicks({ requestId: 'r-1', events });
  await gr.feedback.conversions({ requestId: 'r-1', events: [{ ...events[0]!, value: 19.99 }] });

  return calls.map((call) => {
    const host: Host = call.url.startsWith(DATA) ? 'data' : 'control';
    const origin = host === 'data' ? DATA : CONTROL;
    // Put the concrete id back into its template slot, so the comparison is
    // against the path the schema publishes rather than against one instance.
    const path = call.url
      .slice(origin.length)
      .replace('/v1/submissions/s-1', '/v1/submissions/{submission_id}')
      .replace('/v1/events/batches/b-1', '/v1/events/batches/{batch_id}');
    return { method: call.method, path, host };
  });
}

describe('the route table matches the published schema', () => {
  it('sends every call to a path and method the schema publishes', async () => {
    for (const call of await exercise()) {
      expect(hostOf(call.path, call.method), `${call.method} ${call.path} is not in openapi.json`).not.toBeNull();
    }
  });

  it('sends every call to the host the schema says answers it', async () => {
    for (const call of await exercise()) {
      expect(hostOf(call.path, call.method), `${call.method} ${call.path}`).toBe(call.host);
    }
  });

  it('reaches exactly the routes it claims to', async () => {
    const seen = (await exercise()).map((call) => `${call.method} ${call.path}`).sort();
    const want = EXPECTED.map((route) => `${route.method} ${route.path}`).sort();
    expect(seen).toEqual(want);
  });

  it('covers every data-plane operation in the schema', () => {
    // No list to maintain: a route on the per-tenant host is a route a
    // credential calls, so this fails the day the API grows one.
    const published: string[] = [];
    for (const [path, operations] of Object.entries(schema.paths)) {
      for (const [method, operation] of Object.entries(operations)) {
        if ((operation.servers?.[0]?.url ?? '').includes('{tenant}')) {
          published.push(`${method.toUpperCase()} ${path}`);
        }
      }
    }
    const covered = EXPECTED.filter((route) => route.host === 'data').map(
      (route) => `${route.method} ${route.path}`,
    );
    expect(published.sort()).toEqual(covered.sort());
  });

  it('sends the credential as a bearer token and nothing else as authentication', async () => {
    const { fetch, calls } = scripted([{ body: { request_id: 'r', model_version: null, strategy: 's', fallback_applied: true, items: [], ordering_policy_version: 1, latency_ms: 1 } }]);
    await client({}, fetch).recommendations.forCustomer({ requestId: 'r', customerId: 'c' });

    const headers = calls[0]!.headers;
    expect(headers['Authorization']).toBe(`Bearer ${KEY}`);
    // The credential is verified by `HTTPBearer`; there is no signature scheme,
    // so an SDK sending one would be sending something nothing checks.
    expect(Object.keys(headers).map((key) => key.toLowerCase())).not.toContain('x-signature');
    expect(Object.keys(headers).map((key) => key.toLowerCase())).not.toContain('x-timestamp');
    // Nor a tenant header: the tenant is in the hostname and in the credential.
    expect(JSON.stringify(headers)).not.toContain(TENANT);
  });

  it('does not send Idempotency-Key, because nothing reads it', async () => {
    // `apps/control_api/main.py` allows the header through CORS and no handler
    // calls `Header(...)` for it. The real key is in the body — `batch_id` here.
    const { fetch, calls } = scripted([
      {
        status: 202,
        body: {
          submission_id: 's', kind: 'event_batch', status: 'processing', stage: 'received',
          reference: 'b-1', counts: { received: 0, accepted: 0, updated: 0, skipped: 0, failed: 0 },
          errors: [], error_count: 0, failure_code: null,
          submitted_at: '2026-08-24T10:00:00Z', completed_at: null,
        },
      },
    ]);
    await client({}, fetch).events.submitBatch({
      batchId: 'b-1',
      events: [{ eventId: 'e', customerId: 'c', externalProductId: 'p', eventType: 'view', occurredAt: new Date() }],
    });

    expect(Object.keys(calls[0]!.headers).map((k) => k.toLowerCase())).not.toContain('idempotency-key');
    expect((calls[0]!.body as { batch_id: string }).batch_id).toBe('b-1');
  });
});
