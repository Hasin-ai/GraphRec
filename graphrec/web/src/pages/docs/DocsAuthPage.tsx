import { Link } from "react-router-dom";
import { DocsCodeTabs } from "../../docs/DocsCodeTabs";

export function DocsAuthPage() {
  const apiKeyCurl = `# Calling GraphRec Storefront API with an API key
curl -X GET "https://api.graphrec.io/v1/products?limit=10" \\
  -H "Authorization: ApiKey gr_live_your_storefront_key" \\
  -H "Accept: application/json"`;

  const apiKeyPython = `from graphrec_sdk import GraphRec

# Initialize with Storefront or Tenant API key
client = GraphRec(
    base_url="https://api.graphrec.io",
    api_key="gr_live_your_storefront_key"
)

# Authenticated call
products = client.tenant.catalog.list(limit=10)   # needs the catalog:read scope`;

  const apiKeyJs = `// Browser / Node.js fetch with API Key
const response = await fetch("https://api.graphrec.io/v1/products?limit=10", {
  method: "GET",
  headers: {
    "Authorization": "ApiKey gr_live_your_storefront_key",
    "Accept": "application/json"
  }
});
const data = await response.json();`;

  const bearerCurl = `# Calling GraphRec Management API with a Bearer JWT
curl -X GET "https://api.graphrec.io/v1/tenant/api-keys" \\
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \\
  -H "Accept: application/json"`;

  return (
    <div className="docs-page">
      <header className="docs-page-header">
        <div className="docs-breadcrumbs">
          <Link to="/docs">Docs</Link>
          <span className="separator">/</span>
          <span>Authentication & Tenancy</span>
        </div>
        <h1>Authentication & Multi-Tenancy</h1>
        <p className="lead">
          Learn how GraphRec secures API endpoints, validates caller identities across multi-tenant boundaries, and scopes API keys.
        </p>
      </header>

      {/* Overview */}
      <section id="overview" className="docs-section">
        <h2>Overview</h2>
        <p>
          GraphRec strictly enforces tenant isolation across all endpoints. Every resource—products, shopper events, model training cohorts,
          and inference checkpoints—belongs to an isolated workspace tenant.
        </p>
        <div className="docs-callout docs-callout-info">
          <div className="docs-callout-title">Credential Schemes</div>
          <p>
            GraphRec supports two credential schemes depending on the caller type:
          </p>
          <ul>
            <li><strong>ApiKey Scheme</strong>: Used by e-commerce frontends, backend microservices, and SDK integrations.</li>
            <li><strong>Bearer JWT Scheme</strong>: Used by dashboard console sessions and tenant team members.</li>
            <li><strong>Operator Secret Scheme</strong>: Reserved exclusively for internal cluster administrators on <code>/v1/platform/*</code> routes.</li>
          </ul>
        </div>
      </section>

      {/* Header Contract */}
      <section id="headers" className="docs-section">
        <h2>HTTP Header Contract</h2>
        <p>All HTTP requests sent to GraphRec must adhere to the following header specifications:</p>

        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>Header</th>
                <th>Required</th>
                <th>Format / Value</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>Authorization</code></td>
                <td><span className="badge badge-success">Required</span></td>
                <td><code>ApiKey &lt;secret_key&gt;</code> or <code>Bearer &lt;token&gt;</code></td>
                <td>Credentials for authenticating the tenant context and scopes.</td>
              </tr>
              <tr>
                <td><code>Content-Type</code></td>
                <td><span className="badge badge-warning">On POST/PUT</span></td>
                <td><code>application/json</code> (or <code>multipart/form-data</code> for uploads)</td>
                <td>Required on all mutation endpoints. Requests without this header return HTTP 400.</td>
              </tr>
              <tr>
                <td><code>Accept</code></td>
                <td><span className="badge badge-neutral">Recommended</span></td>
                <td><code>application/json</code></td>
                <td>Informs the server that the client expects a JSON response payload.</td>
              </tr>
              <tr>
                <td><code>X-Correlation-ID</code></td>
                <td><span className="badge badge-neutral">Optional</span></td>
                <td><code>UUID</code> string (e.g. <code>b1a2c3d4-...</code>)</td>
                <td>Pass your distributed trace ID. If omitted, GraphRec generates one and returns it in response headers.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* API Key Authentication */}
      <section id="api-keys" className="docs-section">
        <h2>API Key Authentication</h2>
        <p>
          API keys are the standard authentication mechanism for the Python SDK and direct HTTP integrations. Keys are prefixed with
          <code>gr_live_</code> (production) or <code>gr_test_</code> (staging sandbox).
        </p>

        <DocsCodeTabs
          title="Authenticating with an API Key"
          curl={apiKeyCurl}
          python={apiKeyPython}
          javascript={apiKeyJs}
        />

        <div className="docs-callout docs-callout-warning">
          <div className="docs-callout-title">Security Best Practice</div>
          <p>
            Never expose write-capable API keys or keys with <code>models:write</code> in client-side single-page applications. Store your
            secret keys in secure environment variables (<code>GRAPHREC_API_KEY</code>) on your backend server.
          </p>
        </div>
      </section>

      {/* Key Scopes Matrix */}
      <section id="scopes" className="docs-section">
        <h2>Permission Scopes Matrix</h2>
        <p>
          When provisioning API keys in the dashboard or via <code>POST /v1/api-keys</code>, you can restrict each key to specific permission scopes:
        </p>

        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>Scope</th>
                <th>Category</th>
                <th>Permitted Operations</th>
                <th>Typical Caller</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>catalog:read</code></td>
                <td>Catalog</td>
                <td>List products, search inventory, retrieve product metadata</td>
                <td>Storefront web servers</td>
              </tr>
              <tr>
                <td><code>catalog:write</code></td>
                <td>Catalog</td>
                <td>Bulk upsert items, sync inventories, delete items</td>
                <td>ERP & CMS sync workers</td>
              </tr>
              <tr>
                <td><code>events:write</code></td>
                <td>Telemetry</td>
                <td>Record shopper views, clicks, cart adds, purchases, wishlist events</td>
                <td>Analytics pipeline, store client</td>
              </tr>
              <tr>
                <td><code>recommendations:read</code></td>
                <td>Inference</td>
                <td>Query DGSR personalized recommendations, session recs, similar items</td>
                <td>Storefront rendering layer</td>
              </tr>
              <tr>
                <td><code>models:read</code></td>
                <td>ML Engine</td>
                <td>Inspect model training status, metrics, checkpoints, serving status</td>
                <td>MLOps dashboards</td>
              </tr>
              <tr>
                <td><code>models:write</code></td>
                <td>ML Engine</td>
                <td>Trigger DGSR training jobs, deploy model versions, rollback checkpoints</td>
                <td>Automated training pipelines</td>
              </tr>
              <tr>
                <td><code>admin</code></td>
                <td>Management</td>
                <td>Manage API keys, invite tenant members, manage billing and subscriptions</td>
                <td>Tenant Administrator</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Bearer JWT Authentication */}
      <section id="bearer-tokens" className="docs-section">
        <h2>Dashboard Bearer Tokens</h2>
        <p>
          When human operators interact with the GraphRec web console, authentication uses JSON Web Tokens (JWT) signed with HMAC-SHA256.
          Tokens expire after 24 hours and include the user's role and tenant membership claims.
        </p>

        <DocsCodeTabs
          title="Bearer Token Request"
          curl={bearerCurl}
        />
      </section>

      {/* Multi-Tenancy Boundary */}
      <section id="multi-tenancy" className="docs-section">
        <h2>Multi-Tenancy & Data Isolation</h2>
        <p>
          GraphRec is built from the ground up for strict multi-tenant isolation:
        </p>
        <ul>
          <li>
            <strong>Row-Level Tenant Partitioning:</strong> All database queries automatically filter by the tenant ID decoded from the API key.
            It is mathematically impossible for one tenant to query another tenant's products, shopper histories, or models.
          </li>
          <li>
            <strong>Isolated Vector & Graph Spaces:</strong> Each tenant's interaction graph and embedding spaces are keyed independently.
            DGSR sequential graphs never cross tenant boundaries.
          </li>
          <li>
            <strong>Independent Rate Limits:</strong> Quotas are enforced on a per-tenant basis so noisy neighbors cannot degrade your
            recommendation latency or ingest throughput.
          </li>
        </ul>
      </section>

      {/* Error Cases */}
      <section id="auth-errors" className="docs-section">
        <h2>Authentication Error Codes</h2>
        <p>If authentication or authorization fails, GraphRec returns an error envelope with HTTP status codes:</p>

        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>HTTP Status</th>
                <th>Error Code</th>
                <th>Cause & Remedy</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>401 Unauthorized</code></td>
                <td><code>authentication_failed</code></td>
                <td>The <code>Authorization</code> header is missing, malformed, or the API key does not exist. Check prefix and credentials.</td>
              </tr>
              <tr>
                <td><code>403 Forbidden</code></td>
                <td><code>insufficient_scope</code></td>
                <td>The API key is valid but lacks the scope required for this endpoint (e.g., trying to bulk upsert with a <code>catalog:read</code> key).</td>
              </tr>
              <tr>
                <td><code>403 Forbidden</code></td>
                <td><code>tenant_inactive</code></td>
                <td>The tenant account is disabled, suspended, or archived. Contact platform support.</td>
              </tr>
              <tr>
                <td><code>401 Unauthorized</code></td>
                <td><code>token_expired</code></td>
                <td>The JWT session token has expired. Log in again or rotate the session token.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
