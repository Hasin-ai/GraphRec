/**
 * `/integration` — the API contract, in one place.
 *
 * Explicitly **not** a playground (§7). Every snippet is copyable and none of
 * them fires: a page that issues real requests from a browser session would be
 * teaching people to authenticate the way this console does, which is exactly
 * the way their server must not.
 *
 * The one live thing on the page is the tenant's own credential prefixes and
 * their scopes, because "which of these calls can my key actually make?" is
 * the question that sends people to support, and the answer is already in the
 * credential list.
 */

import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { credentialsQuery } from '../../api/hooks/operations';
import type { Credential } from '../../api/hooks/operations';
import { QueryState } from '../../components/QueryState';
import { Badge, CopyField, Table } from '../../ui';
import type { Column } from '../../ui';
import { SCOPE_SHORT_LABELS } from '../../lib/enums';
import type { CredentialScope } from '../../lib/enums';
import { formatDate } from '../../lib/format';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'https://api.graphrec.example';

interface Endpoint {
  method: string;
  path: string;
  scope: CredentialScope;
  summary: string;
  request?: string;
  response: string;
}

const ENDPOINTS: readonly Endpoint[] = [
  {
    method: 'POST',
    path: '/v1/products:bulk-upsert',
    scope: 'catalog:write',
    summary:
      'Send your catalogue. Accepted for processing, not applied on the spot — the response is a submission you can poll.',
    request: `{
  "sync_id": "2026-08-24-nightly",
  "mode": "upsert",
  "products": [
    {
      "external_id": "sku-1",
      "title": "Example product",
      "category": "example",
      "price": "19.99",
      "availability": "in_stock",
      "active": true
    }
  ]
}`,
    response: `{
  "submission_id": "…",
  "status": "processing",
  "stage": "received",
  "counts": { "received": 1, "accepted": 0, "updated": 0, "skipped": 0, "failed": 0 }
}`,
  },
  {
    method: 'POST',
    path: '/v1/events',
    scope: 'events:write',
    summary:
      'One interaction. Resending the same event_id confirms the first one rather than counting it twice.',
    request: `{
  "event_id": "11111111-1111-4111-8111-111111111111",
  "customer_id": "customer-1",
  "external_product_id": "sku-1",
  "event_type": "view",
  "occurred_at": "2026-08-24T10:00:00Z"
}`,
    response: `{ "event_id": "…", "status": "accepted" }`,
  },
  {
    method: 'POST',
    path: '/v1/events/batches',
    scope: 'events:write',
    summary: 'Up to a batch of interactions at once. Same idempotency rules, one submission back.',
    request: `{ "batch_id": "…", "events": [ /* as above */ ] }`,
    response: `{ "submission_id": "…", "status": "processing", "stage": "received" }`,
  },
  {
    method: 'GET',
    path: '/v1/submissions/{submission_id}',
    scope: 'events:write',
    summary: 'How a batch went, including a per-item list of anything rejected.',
    response: `{
  "submission_id": "…",
  "status": "succeeded",
  "stage": "completed",
  "counts": { "received": 100, "accepted": 98, "updated": 0, "skipped": 0, "failed": 2 },
  "errors": [ { "ref": "sku-9", "reason": "…" } ]
}`,
  },
  {
    method: 'POST',
    path: '/v1/recommendations',
    scope: 'recommendations:read',
    summary: 'Ask for recommendations for one customer. This is the call in your hot path.',
    request: `{ "customer_id": "customer-1", "limit": 10 }`,
    response: `{
  "items": [ { "external_product_id": "sku-1", "score": 0.91 } ],
  "model_version": 7,
  "fallback": false
}`,
  },
  {
    method: 'POST',
    path: '/v1/recommendations/feedback',
    scope: 'recommendations:read',
    summary: 'Tell us what happened to a set of recommendations, so the next model is better.',
    request: `{ "request_id": "…", "external_product_id": "sku-1", "outcome": "clicked" }`,
    response: `{ "status": "accepted" }`,
  },
];

/** The four classes every error belongs to, and what to do about each. */
const ERROR_CLASSES = [
  {
    name: 'validation',
    status: '422',
    meaning: 'The request is malformed or a field is wrong. `field_errors` says which.',
    action: 'Fix and resend. Retrying unchanged will fail identically.',
  },
  {
    name: 'conflict',
    status: '409',
    meaning: 'The request contradicts current state — a duplicate name, a version already active.',
    action: 'Re-read the resource before deciding what to do.',
  },
  {
    name: 'limit',
    status: '429',
    meaning: 'You are over a rate or quota limit. `retry_after_seconds` says how long.',
    action: 'Back off for that long, then retry. Do not retry immediately.',
  },
  {
    name: 'unavailable',
    status: '503',
    meaning: 'Something on our side is temporarily down.',
    action: 'Retry with backoff. Quote the reference if it persists.',
  },
];

export function IntegrationRoute() {
  const credentials = useQuery(credentialsQuery());

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Integration</h1>
        <p className="page__lede">
          Everything your server needs to talk to us. Nothing on this page sends a request — copy
          what you need and run it from your own code, where the credential belongs.
        </p>
      </div>

      <section className="card">
        <h2 className="card__title">Base URL and authentication</h2>
        <CopyField label="Base URL" value={BASE_URL} />
        <p className="page__lede">
          Every call carries your API key in the <code>Authorization</code> header. The key is
          issued once on <Link to="/credentials">Credentials</Link> and never shown again, so store
          it where your application reads its secrets — not in the browser, and not in your
          repository.
        </p>
        <pre className="snippet">
          <code>{`curl -X POST ${BASE_URL}/v1/events \\
  -H "Authorization: Bearer grk_live_…" \\
  -H "Content-Type: application/json" \\
  -d '{"event_id":"…","customer_id":"…","external_product_id":"…","event_type":"view"}'`}</code>
        </pre>
      </section>

      <section className="card">
        <h2 className="card__title">Your credentials</h2>
        <p className="page__lede">
          What these keys may do. A call outside a key's scopes is refused with{' '}
          <code>403</code> whatever else is true about it.
        </p>
        <QueryState
          query={credentials}
          shape="table"
          columns={4}
          label="your credentials"
          isEmpty={(data) => data.credentials.length === 0}
          empty={{
            headline: 'No credentials yet',
            body: 'Issue one before you write any of this code.',
            action: <Link to="/credentials">Go to credentials</Link>,
          }}
        >
          {(data) => <CredentialTable credentials={data.credentials} />}
        </QueryState>
      </section>

      <section>
        <h2 className="eyebrow">Endpoints</h2>
        {ENDPOINTS.map((endpoint) => (
          <EndpointCard key={`${endpoint.method} ${endpoint.path}`} endpoint={endpoint} />
        ))}
      </section>

      <section className="card">
        <h2 className="card__title">Identifiers and retries</h2>
        <p className="page__lede">
          Three fields are yours to choose and ours to deduplicate on:{' '}
          <code>external_id</code> for a product, <code>event_id</code> for an interaction, and{' '}
          <code>sync_id</code> or <code>batch_id</code> for a submission. Send the same one twice
          and the second call confirms the first rather than applying it again. That is what makes
          a retry after a timeout safe: you do not need to know whether the first attempt arrived.
        </p>
      </section>

      <section className="card">
        <h2 className="card__title">When something is refused</h2>
        <p className="page__lede">
          Every failure has the same shape, and every one carries a <code>reference</code>. Log it.
          It is what lets us find your exact request.
        </p>
        <pre className="snippet">
          <code>{`{
  "class": "validation",
  "code": "product_invalid",
  "reason": "A human-readable sentence you may show your own users.",
  "reference": "req_01J…",
  "field_errors": [ { "field": "price", "message": "…" } ],
  "retryable": false,
  "retry_after_seconds": null
}`}</code>
        </pre>
        <Table
          caption="Error classes"
          columns={[
            { key: 'class', header: 'Class', cell: (row) => <code>{row.name}</code> },
            { key: 'status', header: 'Status', cell: (row) => row.status },
            { key: 'meaning', header: 'What it means', cell: (row) => row.meaning },
            { key: 'action', header: 'What to do', cell: (row) => row.action },
          ]}
          rows={ERROR_CLASSES}
          rowKey={(row) => row.name}
        />
      </section>
    </div>
  );
}

function CredentialTable({ credentials }: { credentials: readonly Credential[] }) {
  const columns: readonly Column<Credential>[] = [
    { key: 'name', header: 'Name', cell: (row) => row.name },
    { key: 'prefix', header: 'Prefix', cell: (row) => <code>{row.visible_prefix}</code> },
    {
      key: 'scopes',
      header: 'May call',
      cell: (row) =>
        row.scopes
          .map((scope) => SCOPE_SHORT_LABELS[scope as CredentialScope] ?? scope)
          .join(', '),
    },
    {
      key: 'state',
      header: 'State',
      cell: (row) => <Badge domain="credential" value={row.state} />,
    },
    { key: 'expires', header: 'Expires', cell: (row) => formatDate(row.expires_at) },
  ];

  return (
    <Table
      caption="Your credentials and their scopes"
      columns={columns}
      rows={credentials}
      rowKey={(row) => row.key_id}
    />
  );
}

function EndpointCard({ endpoint }: { endpoint: Endpoint }) {
  return (
    <section className="card">
      <h3 className="card__title">
        <code>
          {endpoint.method} {endpoint.path}
        </code>
      </h3>
      <p className="page__lede">{endpoint.summary}</p>
      <p className="page__lede">
        Requires <code>{endpoint.scope}</code>.
      </p>
      {endpoint.request ? (
        <>
          <h4 className="eyebrow">Request</h4>
          <pre className="snippet">
            <code>{endpoint.request}</code>
          </pre>
          <CopyField label={`${endpoint.path} request body`} value={endpoint.request} />
        </>
      ) : null}
      <h4 className="eyebrow">Response</h4>
      <pre className="snippet">
        <code>{endpoint.response}</code>
      </pre>
    </section>
  );
}
