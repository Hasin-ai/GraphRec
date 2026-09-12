import { apiKeys } from "../../api";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDateTime } from "../../lib/format";
import { SCOPE_SHORT } from "../../lib/scopes";
import { Page } from "../../ui/Page";
import { Cell, DefinitionList, Panel, PanelTable, Snippet } from "../../ui/primitives";

const SNIPPETS = {
  bulk: `POST /v1/products:bulk-upsert
Authorization: ApiKey gr_live_...
{
  "products": [
    {
      "external_id": "SKU-4471",
      "title": "Brass hinge, 75mm",
      "category": "Hardware",
      "price": "8.40",
      "is_active": true,
      "availability_status": "available",
      "metadata": { "brand": "Northgate" }
    }
  ]
}`,
  bulkResponse: `200 OK
{
  "accepted_count": 1, "created_count": 1, "updated_count": 0,
  "skipped_count": 0, "rejected_count": 0, "failures": []
}`,
  event: `POST /v1/events
{
  "event_id": "ev-33810",
  "event_type": "purchase",
  "user_id": "cus-9931",
  "external_product_id": "SKU-6002",
  "occurred_at": "2026-08-14T09:41:02Z",
  "context": { "surface": "product_page" }
}`,
  batch: `POST /v1/events/batches
{ "events": [ /* bounded by MAX_REQUEST_BODY_BYTES */ ] }`,
  duplicate: `200 OK · duplicate confirmed
{ "event_id": "ev-33810", "accepted": true, "duplicate": true, "received_at": "..." }`,
  batchResult: `GET /v1/events/batches/{batch_id}
{
  "id": "…", "status": "completed",
  "accepted_count": 4870, "duplicate_count": 118, "rejected_count": 12,
  "created_at": "..."
}`,
  recommend: `POST /v1/recommendations
{
  "user_id": "cus-9931",
  "top_n": 10,
  "exclude_product_ids": ["SKU-1000"],
  "context": { "surface": "cart" }
}`,
  feedback: `POST /v1/feedback/impressions
{
  "event_id": "imp-1",
  "request_id": "<request_id from the recommendation response>",
  "items": [ { "external_product_id": "SKU-6002", "position": 1 } ]
}`,
  error: `{
  "error": {
    "code": "duplicate_resource",
    "message": "Model version tag 'v1' already exists for this tenant.",
    "correlation_id": "2f0b…",
    "retryable": false
  }
}`,
};

const ERRORS: [string, string, string, string][] = [
  ["validation_failed", "422", "Supplied information cannot be accepted", "details.fields names each field"],
  ["malformed_request", "400", "Headers or body violate the contract", "Content-Type must be application/json"],
  ["authentication_failed", "401", "Credential missing, invalid, revoked or expired", "same message for every cause"],
  ["insufficient_scope", "403", "The credential lacks the required scope", "keys:write, catalog:write, …"],
  ["resource_not_found", "404", "No such resource in this tenant", "another tenant's resource looks identical"],
  ["duplicate_resource / conflict", "409", "State or uniqueness prevents the operation", "model version tag already exists"],
  ["payload_too_large", "413", "Body exceeds the configured limit", "16 KiB JSON; 10 MiB dataset upload"],
  ["rate_limit_exceeded", "429", "A per-source or per-principal limit is exhausted", "Retry-After header is set"],
  ["service_unavailable", "503", "A dependency is unavailable; retry later", "retryable: true"],
];

export function IntegrationPage() {
  const { can } = useSession();
  const keys = useResource(() => (can("keys:write") ? apiKeys.list() : Promise.resolve({ items: [] })), [can("keys:write")]);
  const usable = keys.data?.items.filter((k) => k.status === "active") ?? [];
  const base = `${window.location.origin}/v1`;

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Integration" }]}
      kicker="Reference"
      title="Integration"
      subtitle="The API contract in one place: base URL, authentication, request and response shapes, the error vocabulary and your own credential scopes. This page issues no write requests."
    >
      <DefinitionList
        items={[
          { label: "Base URL", value: base, mono: true, copy: base },
          { label: "Integration authentication", value: "Authorization: ApiKey <credential secret>", mono: true, copy: "Authorization: ApiKey " },
          { label: "Console authentication", value: "Authorization: Bearer <access token>", mono: true },
          { label: "Content type", value: "application/json (multipart/form-data for dataset upload)", mono: true },
          { label: "Idempotency", value: "External identifiers are the idempotency key for products and events; registration takes an Idempotency-Key header." },
          { label: "Correlation", value: "Every response carries X-Correlation-ID; send one to trace a call end to end.", mono: false },
        ]}
      />
      <div className="panels">
        <Panel title="Your active credentials" note={`${usable.length} usable`} body="Only the operations granted to a credential may be performed with it. Anything else is rejected with 403 insufficient_scope before the operation is accepted.">
          {usable.length ? (
            <PanelTable
              columns={["Prefix", "Granted operations", "Expires"]}
              rows={usable.map((k) => (
                <tr key={k.id}>
                  <Cell mono>{k.prefix}…</Cell>
                  <Cell muted>{k.scopes.map((s) => SCOPE_SHORT[s] ?? s).join(" · ")}</Cell>
                  <Cell mono>{fmtDateTime(k.expires_at)}</Cell>
                </tr>
              ))}
            />
          ) : (
            <p className="p-body">No usable credential yet. Create one under API Credentials.</p>
          )}
        </Panel>
        <Panel title="Catalog synchronization" body="Bulk upsert is bounded by the request body limit. Individual invalid items are reported as failures without discarding the accepted remainder.">
          <div className="snippets">
            <Snippet label="POST /v1/products:bulk-upsert" code={SNIPPETS.bulk} />
            <Snippet label="Response" code={SNIPPETS.bulkResponse} />
          </div>
        </Panel>
        <Panel title="Event submission" body="Single and batch share one event shape. A repeated event identifier is confirmed as a duplicate, which is a success outcome, not an error.">
          <div className="snippets">
            <Snippet label="POST /v1/events" code={SNIPPETS.event} />
            <Snippet label="POST /v1/events/batches" code={SNIPPETS.batch} />
            <Snippet label="Duplicate confirmed" code={SNIPPETS.duplicate} />
            <Snippet label="Batch result" code={SNIPPETS.batchResult} />
          </div>
        </Panel>
        <Panel title="Recommendation request and feedback" body="Server-to-server only. These operations have no screen in this console; the fallback rate and serving metrics on Service Status are their only trace here. Scoring is a placeholder in this release.">
          <div className="snippets">
            <Snippet label="POST /v1/recommendations" code={SNIPPETS.recommend} />
            <Snippet label="POST /v1/feedback/impressions | clicks | conversions" code={SNIPPETS.feedback} />
          </div>
        </Panel>
        <Panel title="Error vocabulary" body="Every failure carries a correlation identifier. Payloads and credentials never appear in an error body.">
          <PanelTable
            columns={["Code", "HTTP", "Meaning", "Note"]}
            rows={ERRORS.map((r) => (
              <tr key={r[0]}>
                <Cell mono>{r[0]}</Cell>
                <Cell mono>{r[1]}</Cell>
                <Cell>{r[2]}</Cell>
                <Cell muted>{r[3]}</Cell>
              </tr>
            ))}
          />
          <Snippet label="Error body" code={SNIPPETS.error} />
        </Panel>
      </div>
    </Page>
  );
}
