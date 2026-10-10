import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { SDK_METHODS, type SdkMethodDoc } from "../../docs/docsData";
import { DocsCodeTabs } from "../../docs/DocsCodeTabs";
import { Icon } from "../../ui/icons";

export function DocsSdkPage() {
  const { hash } = useLocation();
  const [filterQuery, setFilterQuery] = useState("");

  const filteredMethods = SDK_METHODS.filter((m) => {
    if (!filterQuery.trim()) return true;
    const q = filterQuery.toLowerCase();
    return (
      m.name.toLowerCase().includes(q) ||
      m.namespace.toLowerCase().includes(q) ||
      m.description.toLowerCase().includes(q) ||
      m.signature.toLowerCase().includes(q)
    );
  });

  const installCode = `# Install using pip
pip install graphrec-sdk

# Or with poetry
poetry add graphrec-sdk`;

  const initSyncCode = `from graphrec_sdk import GraphRec

client = GraphRec(
    base_url="https://api.graphrec.io",   # or http://localhost:8010 for local dev
    api_key="gr_live_YOUR_STOREFRONT_KEY",
    timeout=5.0,                         # 5 second HTTP timeout
    max_retries=3                        # Automatic exponential backoff
)

# Test connectivity
status = client.storefront.health()
print(f"GraphRec API Status: {status['status']}")`;

  const initAsyncCode = `import asyncio
from graphrec_sdk import AsyncGraphRec

async def main():
    async with AsyncGraphRec(
        base_url="https://api.graphrec.io",
        api_key="gr_live_YOUR_STOREFRONT_KEY"
    ) as client:
        recs = await client.storefront.recommendations.get(
            user_id="user_123",
            top_n=5
        )
        print(recs)

asyncio.run(main())`;

  const catalogSyncCode = `from graphrec_sdk import GraphRec
from graphrec_sdk.ecommerce import CatalogSync

client = GraphRec(api_key="gr_live_YOUR_STOREFRONT_KEY")

# Generator or list of products
products = [
    {
        "external_id": f"SKU-{i}",
        "title": f"Summer Product {i}",
        "price": "29.99",
        "category": "Apparel",
        "tags": ["summer", "new"]
    }
    for i in range(1000)
]

# Sync automatically chunks into batches of 250 to respect payload limits
sync = CatalogSync(client, chunk_size=250)
summary = sync.run(products)

print(f"Total synced: {summary.total_items}")
print(f"Batches: {summary.batches_sent}")
print(f"Duration: {summary.duration_seconds:.2f}s")`;

  const eventTrackerCode = `from graphrec_sdk import GraphRec
from graphrec_sdk.ecommerce import EventTracker

client = GraphRec(api_key="gr_live_YOUR_STOREFRONT_KEY")

# Thread-safe buffer flushes in background or on exit
with EventTracker(client, batch_size=50, flush_interval=5.0) as tracker:
    tracker.view(user_id="usr_88", external_product_id="SKU-100")
    tracker.click(user_id="usr_88", external_product_id="SKU-100")
    tracker.add_to_cart(user_id="usr_88", external_product_id="SKU-100", quantity=1)
    tracker.purchase(user_id="usr_88", external_product_id="SKU-100", order_id="ORD-90210")
# Context exit automatically flushes any remaining queued events`;

  return (
    <div className="docs-page">
      <header className="docs-page-header">
        <div className="docs-breadcrumbs">
          <Link to="/docs">Docs</Link>
          <span className="separator">/</span>
          <span>Python SDK Reference</span>
        </div>
        <h1>Python SDK Reference</h1>
        <p className="lead">
          Official, production-ready Python SDK (<code>graphrec-sdk</code>) with synchronous and asynchronous clients,
          built-in retries, connection pooling, and e-commerce ingestion helpers.
        </p>
      </header>

      {/* Installation */}
      <section id="installation" className="docs-section">
        <h2>Installation</h2>
        <p>The SDK supports Python 3.9+ and has minimal third-party dependencies (HTTPX, Pydantic, and Tenacity):</p>
        <DocsCodeTabs title="Terminal" curl={installCode} />
      </section>

      {/* Client Configuration */}
      <section id="configuration" className="docs-section">
        <h2>Client Initialization</h2>
        <p>
          Configure the client with your API key and base URL. Both synchronous (<code>GraphRec</code>) and asynchronous (<code>AsyncGraphRec</code>)
          clients share the same API surface.
        </p>

        <DocsCodeTabs
          title="Synchronous Initialization"
          python={initSyncCode}
        />

        <DocsCodeTabs
          title="Asynchronous (async/await) Initialization"
          python={initAsyncCode}
        />

        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Type</th>
                <th>Default</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>base_url</code></td>
                <td><code>str</code></td>
                <td><code>"https://api.graphrec.io"</code></td>
                <td>Root URL of the GraphRec cluster or local proxy.</td>
              </tr>
              <tr>
                <td><code>api_key</code></td>
                <td><code>Optional[str]</code></td>
                <td><code>os.getenv("GRAPHREC_API_KEY")</code></td>
                <td>Storefront or Tenant secret API key.</td>
              </tr>
              <tr>
                <td><code>bearer_token</code></td>
                <td><code>Optional[str]</code></td>
                <td><code>None</code></td>
                <td>JWT Bearer token for tenant dashboard console sessions.</td>
              </tr>
              <tr>
                <td><code>timeout</code></td>
                <td><code>float</code></td>
                <td><code>10.0</code></td>
                <td>Total HTTP request timeout in seconds.</td>
              </tr>
              <tr>
                <td><code>max_retries</code></td>
                <td><code>int</code></td>
                <td><code>3</code></td>
                <td>Maximum automatic retry attempts for transient 429 and 503 errors.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Namespaces Architecture */}
      <section id="namespaces" className="docs-section">
        <h2>Client Namespaces</h2>
        <p>The client organizes operations into 3 hierarchical namespaces according to caller responsibilities:</p>

        <div className="docs-grid-3">
          <div className="docs-card">
            <h3 id="storefront">client.storefront</h3>
            <p>High-throughput, low-latency endpoints optimized for shopper-facing storefronts.</p>
            <ul>
              <li><code>.recommendations.get(...)</code></li>
              <li><code>.recommendations.similar(...)</code></li>
              <li><code>.events.record(...)</code></li>
              <li><code>.catalog.get_product(...)</code></li>
            </ul>
          </div>

          <div className="docs-card">
            <h3 id="tenant">client.tenant</h3>
            <p>Management, MLOps, and catalog administrative endpoints for workspace owners.</p>
            <ul>
              <li><code>.catalog.bulk_upsert(...)</code></li>
              <li><code>.models.train(...)</code></li>
              <li><code>.models.get_status(...)</code></li>
              <li><code>.api_keys.create(...)</code></li>
            </ul>
          </div>

          <div className="docs-card">
            <h3 id="platform">client.platform</h3>
            <p>Cross-tenant administrative endpoints reserved for cluster root operators.</p>
            <ul>
              <li><code>.tenants.list(...)</code></li>
              <li><code>.overview.metrics(...)</code></li>
              <li><code>.quotas.update(...)</code></li>
            </ul>
          </div>
        </div>
      </section>

      {/* E-Commerce Ingestion Helpers */}
      <section id="ecommerce" className="docs-section">
        <h2>E-Commerce Ingestion Helpers</h2>
        <p>
          The <code>graphrec_sdk.ecommerce</code> module provides high-level abstractions designed for e-commerce catalog syncs
          and interaction event pipelines:
        </p>

        <h3>1. CatalogSync</h3>
        <p>
          Uploads product catalogs of arbitrary size by batching items into chunks of 250, honoring the 16 KiB HTTP payload limit,
          and automatically handling rate limiting backoff:
        </p>
        <DocsCodeTabs title="CatalogSync Example" python={catalogSyncCode} />

        <h3>2. EventTracker</h3>
        <p>
          Thread-safe background event aggregator that records views, clicks, cart modifications, and purchases without slowing down
          shopper web request threads:
        </p>
        <DocsCodeTabs title="EventTracker Example" python={eventTrackerCode} />
      </section>

      {/* SDK Methods Reference */}
      <section id="methods" className="docs-section">
        <h2>SDK Methods Reference</h2>
        <p>Verified public methods exposed on the <code>GraphRec</code> client:</p>

        <div className="docs-ref-search-box" style={{ marginBottom: "1.5rem" }}>
          <Icon name="search" size={14} />
          <input
            type="search"
            placeholder="Search SDK methods by name or signature..."
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            aria-label="Filter SDK methods"
          />
        </div>

        <div className="docs-sdk-methods-list">
          {filteredMethods.map((m) => (
            <SdkMethodCard
              key={m.name}
              method={m}
              isHighlighted={hash === `#${m.name.replace(/[^a-zA-Z0-9_-]/g, "-")}`}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

function SdkMethodCard({ method, isHighlighted }: { method: SdkMethodDoc; isHighlighted: boolean }) {
  const anchorId = method.name.replace(/[^a-zA-Z0-9_-]/g, "-");

  return (
    <article id={anchorId} className={`docs-endpoint-card ${isHighlighted ? "highlighted" : ""}`}>
      <header className="docs-endpoint-header">
        <div className="docs-endpoint-title-row">
          <code className="docs-method-title">{method.name}</code>
          <span className="docs-scope-badge">{method.namespace}</span>
        </div>
        <p className="docs-endpoint-summary">{method.description}</p>
        <pre className="docs-signature-pre">
          <code>{method.signature}</code>
        </pre>
      </header>

      <div className="docs-endpoint-body">
        {method.parameters.length > 0 && (
          <div className="docs-sub-section">
            <h4>Arguments</h4>
            <div className="docs-table-wrapper">
              <table className="docs-table docs-param-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Required</th>
                    <th>Default</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {method.parameters.map((p) => (
                    <tr key={p.name}>
                      <td><code>{p.name}</code></td>
                      <td><code>{p.type}</code></td>
                      <td>{p.required ? <span className="badge badge-warning">Required</span> : <span className="badge badge-neutral">Optional</span>}</td>
                      <td>{p.default ? <code>{p.default}</code> : "—"}</td>
                      <td>{p.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="docs-sub-section">
          <h4>Returns</h4>
          <p><code>{method.returns}</code></p>
        </div>

        {method.raises.length > 0 && (
          <div className="docs-sub-section">
            <h4>Raises</h4>
            <div className="docs-tag-pills">
              {method.raises.map((err) => (
                <span key={err} className="badge badge-danger">
                  {err}
                </span>
              ))}
            </div>
          </div>
        )}

        {method.example && (
          <div className="docs-sub-section">
            <h4>Runnable Example</h4>
            <DocsCodeTabs title="Python" python={method.example} />
          </div>
        )}
      </div>
    </article>
  );
}
