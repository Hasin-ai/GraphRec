import { Link } from "react-router-dom";
import { ERROR_CODES, PLAN_LIMITS } from "../../docs/docsData";
import { DocsCodeTabs } from "../../docs/DocsCodeTabs";

export function DocsErrorsLimitsPage() {
  const errorEnvelopeJson = `{
  "error": {
    "code": "insufficient_scope",
    "message": "API key lacks required scope 'catalog:write'",
    "correlation_id": "9a38f420-1b5e-49b8-a764-cf368d19ab42",
    "retryable": false,
    "details": {
      "required_scope": "catalog:write",
      "granted_scopes": ["catalog:read", "recommendations:read"]
    }
  }
}`;

  return (
    <div className="docs-page">
      <header className="docs-page-header">
        <div className="docs-breadcrumbs">
          <Link to="/docs">Docs</Link>
          <span className="separator">/</span>
          <span>Errors, Limits & Changelog</span>
        </div>
        <h1>Errors, Limits & Changelog</h1>
        <p className="lead">
          Standardized error envelope contracts, HTTP status code dictionary, sliding-window rate limits, payload constraints, and release notes.
        </p>
      </header>

      {/* Error Envelope */}
      <section id="error-envelope" className="docs-section">
        <h2>Standard Error Envelope</h2>
        <p>
          Every 4xx and 5xx response from GraphRec returns a uniform JSON error envelope.
          Clients and SDK callers can reliably parse <code>error.code</code> and <code>error.retryable</code> without parsing arbitrary error strings.
        </p>

        <DocsCodeTabs title="HTTP Error Response (JSON)" curl={errorEnvelopeJson} />

        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>Field</th>
                <th>Type</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>error.code</code></td>
                <td><code>string</code></td>
                <td>Machine-readable, deterministic error enum identifier.</td>
              </tr>
              <tr>
                <td><code>error.message</code></td>
                <td><code>string</code></td>
                <td>Human-readable explanation of why the request failed.</td>
              </tr>
              <tr>
                <td><code>error.correlation_id</code></td>
                <td><code>string (UUID)</code></td>
                <td>Unique trace ID associated with the request log. Include this ID when contacting support.</td>
              </tr>
              <tr>
                <td><code>error.retryable</code></td>
                <td><code>boolean</code></td>
                <td>Indicates whether the client may safely retry the operation after backoff.</td>
              </tr>
              <tr>
                <td><code>error.details</code></td>
                <td><code>object</code></td>
                <td>Optional map containing validation errors, missing fields, or quota numbers.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Error Codes Vocabulary */}
      <section id="error-codes" className="docs-section">
        <h2>Error Vocabulary</h2>
        <p>The standard error codes emitted by GraphRec:</p>

        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>HTTP Status</th>
                <th>Error Code</th>
                <th>Meaning</th>
                <th>Retryable</th>
              </tr>
            </thead>
            <tbody>
              {ERROR_CODES.map((err) => (
                <tr key={err.code}>
                  <td>
                    <span className={`badge ${err.status < 500 ? "badge-warning" : "badge-danger"}`}>
                      HTTP {err.status}
                    </span>
                  </td>
                  <td><code>{err.code}</code></td>
                  <td>{err.meaning}</td>
                  <td>
                    {err.retryable ? (
                      <span className="badge badge-success">Yes (with backoff)</span>
                    ) : (
                      <span className="badge badge-neutral">No</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Rate Limits & Headers */}
      <section id="rate-limits" className="docs-section">
        <h2>Rate Limits & Sliding Windows</h2>
        <p>
          GraphRec enforces per-tenant sliding-window token bucket rate limits to ensure cluster fairness and prevent runaway traffic:
        </p>

        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>Response Header</th>
                <th>Example Value</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>X-RateLimit-Limit</code></td>
                <td><code>1000</code></td>
                <td>Maximum permitted requests within the current 60-second window.</td>
              </tr>
              <tr>
                <td><code>X-RateLimit-Remaining</code></td>
                <td><code>742</code></td>
                <td>Remaining request quota until the window resets.</td>
              </tr>
              <tr>
                <td><code>X-RateLimit-Reset</code></td>
                <td><code>1700000045</code></td>
                <td>Unix timestamp when the current rate limit window refreshes.</td>
              </tr>
              <tr>
                <td><code>Retry-After</code></td>
                <td><code>2</code></td>
                <td>Sent with HTTP 429. Number of seconds the client must wait before retrying.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Payload Size Limits */}
      <section id="payload-limits" className="docs-section">
        <h2>Payload Size Limits</h2>
        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>Traffic Type</th>
                <th>Size Limit</th>
                <th>Enforcement & Action</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>JSON Mutation Endpoints</td>
                <td><code>16 KiB</code></td>
                <td>Exceeding returns <code>413 payload_too_large</code>. Use <code>CatalogSync</code> or batch ingestion helpers to chunk data.</td>
              </tr>
              <tr>
                <td>Multipart Dataset Uploads</td>
                <td><code>50 MiB</code></td>
                <td>Applies to <code>POST /v1/datasets/upload</code> for raw CSV / JSONL interaction files.</td>
              </tr>
              <tr>
                <td>Batch Event Arrays</td>
                <td><code>500 items</code></td>
                <td>Maximum array length in a single <code>POST /v1/events/batch</code> call.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Plan Limits Matrix */}
      <section id="plan-limits" className="docs-section">
        <h2>Workspace Plan Limits</h2>
        <p>Monthly usage quotas across tenant subscription tiers:</p>

        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>Quota Dimension</th>
                <th>Free Tier</th>
                <th>Pro Tier</th>
                <th>Enterprise Tier</th>
              </tr>
            </thead>
            <tbody>
              {PLAN_LIMITS.map((p) => (
                <tr key={p.dimension}>
                  <td><strong>{p.dimension.replace(/_/g, " ")}</strong></td>
                  <td>{p.free}</td>
                  <td><span className="badge badge-success">{p.pro}</span></td>
                  <td><span className="badge badge-primary">{p.enterprise}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Versioning & Changelog */}
      <section id="changelog" className="docs-section">
        <h2>API Versioning & Changelog</h2>
        <p>
          GraphRec uses URI path versioning (<code>/v1/</code>). We adhere to strict backward compatibility guarantees:
        </p>
        <ul>
          <li>We will never remove an existing field from a response without a 6-month deprecation period.</li>
          <li>Adding new optional request parameters or new response fields is considered non-breaking.</li>
          <li>New major features or algorithmic shifts are introduced under new route endpoints or API versions.</li>
        </ul>

        <h3>Release History</h3>
        <div className="docs-changelog-list">
          <div className="docs-changelog-entry">
            <div className="docs-changelog-header">
              <span className="badge badge-success">v1.2.0</span>
              <span className="date">October 2026</span>
            </div>
            <h4>E-Commerce Storefront Reference & Dynamic Graph Rec (DGSR)</h4>
            <ul>
              <li>Added real-time session inference endpoint (<code>POST /v1/recommendations/session</code>).</li>
              <li>Added <code>CatalogSync</code> and <code>EventTracker</code> high-level helpers to Python SDK.</li>
              <li>Added explicit correlation ID tracking (<code>X-Correlation-ID</code>) across all endpoints.</li>
              <li>Interactive API Developer Documentation in web console with cURL, Python SDK, and JavaScript examples.</li>
            </ul>
          </div>

          <div className="docs-changelog-entry">
            <div className="docs-changelog-header">
              <span className="badge badge-neutral">v1.1.0</span>
              <span className="date">August 2026</span>
            </div>
            <h4>Model Serving & Checkpoint Rollbacks</h4>
            <ul>
              <li>Introduced model version registry and <code>/v1/model-versions/{`{version_id}`}:rollback</code>.</li>
              <li>Prometheus metrics export on <code>/metrics</code>.</li>
              <li>Automated hourly snapshot pipeline for training datasets.</li>
            </ul>
          </div>

          <div className="docs-changelog-entry">
            <div className="docs-changelog-header">
              <span className="badge badge-neutral">v1.0.0</span>
              <span className="date">June 2026</span>
            </div>
            <h4>Initial Production Release</h4>
            <ul>
              <li>Core multi-tenant FastAPI service with PostgreSQL and Redis.</li>
              <li>API Key management with fine-grained permission scopes.</li>
              <li>Catalog bulk upsert and interaction event tracking.</li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
