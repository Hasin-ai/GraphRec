import { useState } from "react";
import { Link } from "react-router-dom";
import { apiKeys } from "../../api";
import { apiUrl } from "../../api/client";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDateTime } from "../../lib/format";
import { SCOPE_SHORT } from "../../lib/scopes";
import { Page } from "../../ui/Page";
import { Cell, DefinitionList, Panel, PanelTable, ErrorBanner, Skeleton } from "../../ui/primitives";
import { CodeBlock } from "../../ui/kit";

const SNIPPETS = {
  pythonInstall: `pip install graphrec-sdk`,
  pythonQuickstart: `from graphrec_sdk import GraphRec
from graphrec_sdk.ecommerce import CatalogSync, EventTracker

# Initialize client with your storefront API key
client = GraphRec(base_url="https://api.graphrec.io", api_key="<YOUR_STOREFRONT_API_KEY>")

# 1. Synchronize product catalog
CatalogSync(client).run([
    {
        "external_id": "SKU-4471",
        "title": "Brass hinge, 75mm",
        "price": "8.40",
        "category": "Hardware",
        "metadata": {"brand": "Northgate"}
    }
])

# 2. Track customer interaction events (buffered and batch-uploaded)
with EventTracker(client, batch_size=100, flush_interval=5) as tracker:
    tracker.view("cus-9931", "SKU-4471")
    tracker.add_to_cart("cus-9931", "SKU-4471", quantity=1)
    tracker.purchase("cus-9931", "SKU-4471", order_id="ORD-1001")

# 3. Retrieve ranked recommendations
recs = client.storefront.recommendations.get(
    user_id="cus-9931",
    top_n=10,
    context={"surface": "cart"}
)
for item in recs.items:
    print(f"Rank #{item.position}: {item.external_product_id}")`,

  bulkCurl: `curl -X POST "https://api.graphrec.io/v1/products:bulk-upsert" \\
  -H "Authorization: ApiKey <credential_secret>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "request_id": "sync-2026-10-08-01",
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
  }'`,

  bulkResponse: `200 OK
{
  "sync_id": "sync_89b21a",
  "status": "completed",
  "request_id": "sync-2026-10-08-01",
  "accepted_count": 1,
  "created_count": 1,
  "updated_count": 0,
  "skipped_count": 0,
  "rejected_count": 0,
  "failures": [],
  "outcomes": [{ "external_id": "SKU-4471", "status": "created" }]
}`,

  eventCurl: `curl -X POST "https://api.graphrec.io/v1/events" \\
  -H "Authorization: ApiKey <credential_secret>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "event_id": "ev-33810",
    "event_type": "purchase",
    "user_id": "cus-9931",
    "external_product_id": "SKU-4471",
    "occurred_at": "2026-10-08T12:00:00Z",
    "context": { "surface": "pdp" }
  }'`,

  batchCurl: `curl -X POST "https://api.graphrec.io/v1/events/batches" \\
  -H "Authorization: ApiKey <credential_secret>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "request_id": "batch-1001",
    "events": [
      {
        "event_id": "ev-1",
        "event_type": "view",
        "user_id": "cus-9931",
        "external_product_id": "SKU-4471"
      }
    ]
  }'`,

  recommendCurl: `curl -X POST "https://api.graphrec.io/v1/recommendations" \\
  -H "Authorization: ApiKey <credential_secret>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": "cus-9931",
    "top_n": 10,
    "fallback_allowed": true,
    "context": { "surface": "cart" }
  }'`,

  errorResponse: `409 Conflict
{
  "error": {
    "code": "duplicate_resource",
    "message": "Model version tag 'v1' already exists for this tenant.",
    "correlation_id": "2f0b991a-8e2b-4e6f-9981-d4cb123e4567",
    "retryable": false
  }
}`,
};

const ERRORS: [string, string, string, string][] = [
  ["validation_failed", "422", "Supplied information cannot be accepted", "details.fields names each invalid field"],
  ["malformed_request", "400", "Headers or body violate the contract", "Content-Type must be application/json"],
  ["authentication_failed", "401", "Credential missing, invalid, revoked or expired", "Uniform security message across causes"],
  ["insufficient_scope", "403", "The credential lacks the required scope", "keys:write, catalog:write, events:write, …"],
  ["resource_not_found", "404", "No such resource in this tenant", "Multi-tenant isolated; foreign IDs return 404"],
  ["duplicate_resource / conflict", "409", "State or uniqueness prevents the operation", "Version tag or resource already exists"],
  ["payload_too_large", "413", "Body exceeds the configured limit", "JSON bodies and dataset uploads have distinct limits"],
  ["rate_limit_exceeded", "429", "Per-minute rate limit is exhausted", "Retry-After response header is provided"],
  ["service_unavailable", "503", "A backend dependency is unavailable; retry later", "retryable: true flag included"],
  ["recommendation_unavailable", "503", "No personalized result and fallback disallowed", "Allow fallback or provide user history"],
];

export function IntegrationPage() {
  const { can } = useSession();
  const [activeLang, setActiveLang] = useState<"python" | "curl">("python");
  const keys = useResource(() => (can("keys:write") ? apiKeys.list() : Promise.resolve({ items: [] })), [can("keys:write")]);
  const usable = keys.data?.items.filter((k) => k.status === "active") ?? [];
  const base = new URL(apiUrl("/v1"), window.location.origin).toString();

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Integration" }]}
      kicker="Developer Guide"
      title="Integration"
      subtitle="Step-by-step developer guide and SDK reference for connecting your storefront to GraphRec."
    >
      <div className="tabs" style={{ marginBottom: 16 }}>
        <button
          type="button"
          className={activeLang === "python" ? "active" : ""}
          onClick={() => setActiveLang("python")}
        >
          Python SDK (Recommended)
        </button>
        <button
          type="button"
          className={activeLang === "curl" ? "active" : ""}
          onClick={() => setActiveLang("curl")}
        >
          Direct HTTP / cURL
        </button>
      </div>

      <DefinitionList
        items={[
          { label: "API Base URL", value: base, mono: true, copy: base },
          { label: "SDK Authentication", value: "client = GraphRec(api_key='<KEY>')", mono: true },
          { label: "HTTP Header Authentication", value: "Authorization: ApiKey <credential secret>", mono: true, copy: "Authorization: ApiKey " },
          { label: "Idempotency", value: "External product IDs and event IDs serve as natural idempotency keys; duplicate events are acknowledged safely." },
          { label: "Tracing & Correlation", value: "Every response carries X-Correlation-ID for end-to-end telemetry and debugging." },
        ]}
      />

      <div className="panels">
        {can("keys:write") ? (
          <Panel
            title="Your active API credentials"
            note={keys.data ? `${usable.length} usable` : undefined}
            body="Storefront credentials must hold appropriate scopes (e.g. catalog:write, events:write, recommendations:read)."
          >
            {keys.error ? <ErrorBanner error={keys.error} onRetry={keys.reload} /> : null}
            {!keys.data ? (
              keys.loading ? <Skeleton rows={2} /> : null
            ) : usable.length ? (
              <PanelTable
                columns={["Prefix", "Granted permissions", "Expires"]}
                rows={usable.map((k) => (
                  <tr key={k.id}>
                    <Cell mono>{k.prefix}…</Cell>
                    <Cell muted>{k.scopes.map((s) => SCOPE_SHORT[s] ?? s).join(" · ")}</Cell>
                    <Cell mono>{k.expires_at ? fmtDateTime(k.expires_at) : "No expiry"}</Cell>
                  </tr>
                ))}
              />
            ) : (
              <div style={{ padding: "12px 0" }}>
                <p className="p-body">No usable credentials created yet.</p>
                <Link to="/credentials" className="btn btn-primary btn-sm" style={{ display: "inline-flex", marginTop: 8 }}>
                  Create API credential
                </Link>
              </div>
            )}
          </Panel>
        ) : null}

        {activeLang === "python" ? (
          <>
            <Panel
              title="1. Install the Python SDK"
              body="GraphRec provides an asynchronous and synchronous typed Python client with built-in retries, Pydantic v2 schemas, and e-commerce helpers."
            >
              <CodeBlock code={SNIPPETS.pythonInstall} language="bash" title="Installation" />
            </Panel>

            <Panel
              title="2. Full E-Commerce Quickstart"
              body="Sync your product catalog, buffer interaction events, and retrieve personalized recommendations in under 30 lines of code."
            >
              <CodeBlock code={SNIPPETS.pythonQuickstart} language="python" title="storefront_integration.py" />
            </Panel>
          </>
        ) : (
          <>
            <Panel
              title="1. Catalog Synchronization"
              body="Bulk upsert accepts up to 1,000 items per batch. Results are retained and idempotently queried by request_id."
            >
              <div className="snippets">
                <CodeBlock code={SNIPPETS.bulkCurl} language="bash" title="POST /v1/products:bulk-upsert" />
                <CodeBlock code={SNIPPETS.bulkResponse} language="json" title="Response (200 OK)" />
              </div>
            </Panel>

            <Panel
              title="2. Event Submission"
              body="Stream real-time interaction events (view, add_to_cart, purchase). Repeated event_id values are safely deduplicated."
            >
              <div className="snippets">
                <CodeBlock code={SNIPPETS.eventCurl} language="bash" title="POST /v1/events" />
                <CodeBlock code={SNIPPETS.batchCurl} language="bash" title="POST /v1/events/batches" />
              </div>
            </Panel>

            <Panel
              title="3. Recommendation Inference"
              body="Request ranked recommendations by user ID and storefront surface. Responses name the serving model and fallback state."
            >
              <CodeBlock code={SNIPPETS.recommendCurl} language="bash" title="POST /v1/recommendations" />
            </Panel>
          </>
        )}

        <Panel
          title="Error vocabulary & Status codes"
          body="Every failure carries an error code and correlation ID. Secrets and sensitive customer payloads are never reflected in error messages."
        >
          <PanelTable
            columns={["Code", "HTTP", "Meaning", "Detail"]}
            rows={ERRORS.map((r) => (
              <tr key={r[0]}>
                <Cell mono>{r[0]}</Cell>
                <Cell mono>{r[1]}</Cell>
                <Cell>{r[2]}</Cell>
                <Cell muted>{r[3]}</Cell>
              </tr>
            ))}
          />
          <div style={{ marginTop: 12 }}>
            <CodeBlock code={SNIPPETS.errorResponse} language="json" title="Example error payload" />
          </div>
        </Panel>
      </div>
    </Page>
  );
}
