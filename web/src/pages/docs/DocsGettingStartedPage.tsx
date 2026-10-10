import { Link } from "react-router-dom";
import { DocsCodeTabs } from "../../docs/DocsCodeTabs";

const QUICKSTART_CURL = {
  curl: `# 1. Bulk import your product catalog
curl -X POST "https://api.graphrec.io/v1/products:bulk-upsert" \\
  -H "Authorization: ApiKey gr_live_YOUR_STOREFRONT_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "products": [
      { "external_id": "SKU-100", "title": "Linen Summer Shirt", "price": "49.90", "category": "Apparel" },
      { "external_id": "SKU-205", "title": "Classic Denim Jeans", "price": "79.00", "category": "Apparel" }
    ]
  }'

# 2. Record shopper interaction event
curl -X POST "https://api.graphrec.io/v1/events" \\
  -H "Authorization: ApiKey gr_live_YOUR_STOREFRONT_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": "customer-42",
    "external_product_id": "SKU-100",
    "event_type": "view"
  }'

# 3. Query real-time personalized recommendations
curl -X POST "https://api.graphrec.io/v1/recommendations" \\
  -H "Authorization: ApiKey gr_live_YOUR_STOREFRONT_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": "customer-42",
    "top_n": 10,
    "context": { "surface": "home" }
  }'`,
  python: `from graphrec_sdk import GraphRec
from graphrec_sdk.ecommerce import CatalogSync, EventTracker

# 1. Initialize client with your storefront API key
client = GraphRec(
    base_url="https://api.graphrec.io",
    api_key="gr_live_YOUR_STOREFRONT_KEY"
)

# 2. Synchronize product inventory
CatalogSync(client).run([
    {"external_id": "SKU-100", "title": "Linen Summer Shirt", "price": "49.90", "category": "Apparel"},
    {"external_id": "SKU-205", "title": "Classic Denim Jeans", "price": "79.00", "category": "Apparel"}
])

# 3. Track customer events (buffered and batch-uploaded)
with EventTracker(client, batch_size=100) as tracker:
    tracker.view("customer-42", "SKU-100")
    tracker.add_to_cart("customer-42", "SKU-100", quantity=1)

# 4. Fetch live personalized recommendations
recs = client.storefront.recommendations.get(
    user_id="customer-42",
    top_n=10,
    context={"surface": "home"}
)
for item in recs.items:
    print(f"Rank #{item.position}: {item.external_product_id} (score: {item.score})")`,
  javascript: `// 1. Bulk import catalog
await fetch("https://api.graphrec.io/v1/products:bulk-upsert", {
  method: "POST",
  headers: {
    "Authorization": "ApiKey gr_live_YOUR_STOREFRONT_KEY",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    products: [
      { external_id: "SKU-100", title: "Linen Summer Shirt", price: "49.90", category: "Apparel" }
    ]
  })
});

// 2. Send interaction event
await fetch("https://api.graphrec.io/v1/events", {
  method: "POST",
  headers: {
    "Authorization": "ApiKey gr_live_YOUR_STOREFRONT_KEY",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    user_id: "customer-42",
    external_product_id: "SKU-100",
    event_type: "view"
  })
});

// 3. Query recommendations
const res = await fetch("https://api.graphrec.io/v1/recommendations", {
  method: "POST",
  headers: {
    "Authorization": "ApiKey gr_live_YOUR_STOREFRONT_KEY",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    user_id: "customer-42",
    top_n: 10,
    context: { surface: "home" }
  })
});
const { items, strategy } = await res.json();
console.log("Strategy:", strategy, items);`,
};

export function DocsGettingStartedPage() {
  return (
    <article className="docs-content">
      <div className="docs-page-header">
        <div className="docs-badge-row">
          <span className="docs-pill">Getting Started</span>
          <span className="docs-pill muted">v1.1.0</span>
        </div>
        <h1 className="docs-title">Welcome to GraphRec Developer Documentation</h1>
        <p className="docs-lead">
          GraphRec is a multi-tenant recommendation platform built for e-commerce. It pairs dynamic sequential
          graph neural network modeling (DGSR) with a resilient, high-throughput REST API and typed Python SDK.
        </p>
      </div>

      <section id="what-is-graphrec">
        <h2>What is GraphRec?</h2>
        <p>
          Traditional collaborative filtering models retrain daily or weekly, leaving recommendations blind to what a
          shopper browsed three minutes ago. GraphRec continuously folds every view, cart addition, and purchase into
          the customer's immediate sequential graph context.
        </p>
        <p>
          When you request recommendations, GraphRec combines the customer's trained static embedding with their live
          20-item interaction window—calculating re-ranked items in under <strong>60 milliseconds</strong> without
          retraining the base model weights.
        </p>

        <div className="docs-grid-cards">
          <div className="docs-card">
            <h3>Sub-60ms Serving Latency</h3>
            <p>
              Pre-computed user & item embeddings paired with real-time sequential attention layers deliver instant
              re-ranking at storefront scale.
            </p>
          </div>
          <div className="docs-card">
            <h3>Multi-Tenant Row Isolation</h3>
            <p>
              Every tenant's catalog, interaction stream, trained model checkpoints, and billing quotas are strictly
              partitioned at the database level.
            </p>
          </div>
          <div className="docs-card">
            <h3>Full Attribution Loop</h3>
            <p>
              Measure genuine uplift by tracking recommendation impressions, item clicks, and conversion purchases
              tied to specific recommendation requests.
            </p>
          </div>
          <div className="docs-card">
            <h3>Graceful Degradation</h3>
            <p>
              When a visitor is cold or unauthenticated, GraphRec seamlessly falls back to session-based sequential
              encoding or trending popularity tiers.
            </p>
          </div>
        </div>
      </section>

      <section id="core-concepts">
        <h2>Core Concepts</h2>
        <table className="docs-table">
          <thead>
            <tr>
              <th>Concept</th>
              <th>Description</th>
              <th>API Representation</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Tenant</strong></td>
              <td>An isolated business workspace with dedicated credentials, quota, and catalog.</td>
              <td><code>tenant_id: UUID</code> in JWT claims or API key record</td>
            </tr>
            <tr>
              <td><strong>Product (Item)</strong></td>
              <td>A catalog entry identified by your store's natural SKU, carrying attributes, price, and category.</td>
              <td><code>/v1/products/{`{external_id}`}</code></td>
            </tr>
            <tr>
              <td><strong>Event</strong></td>
              <td>A customer interaction (view, click, add_to_cart, purchase, rating, add_to_wishlist).</td>
              <td><code>POST /v1/events</code> with idempotency key</td>
            </tr>
            <tr>
              <td><strong>Model Version</strong></td>
              <td>An active DGSR checkpoint trained on a specific cohort snapshot of catalog and events.</td>
              <td><code>/v1/model-versions/{`{version_id}`}</code></td>
            </tr>
            <tr>
              <td><strong>Recommendation Strategy</strong></td>
              <td>The inference path used: <code>personalized</code>, <code>session</code>, or <code>popular_fallback</code>.</td>
              <td>Returned in <code>strategy</code> response field</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section id="quickstart">
        <h2>5-Minute Quickstart</h2>
        <p>Get up and running with GraphRec in three simple steps.</p>

        <h3>Step 1: Get Your API Key</h3>
        <p>
          Sign in to the <Link to="/login">GraphRec Console</Link>, navigate to <strong>Integrate &rarr; API Credentials</strong>,
          and generate a storefront credential with <code>catalog:write</code>, <code>events:write</code>, and <code>recommendations:read</code> scopes.
        </p>

        <h3>Step 2: Install the Python SDK</h3>
        <pre className="docs-code-pre">
          <code>pip install graphrec-sdk</code>
        </pre>

        <h3>Step 3: Ingest Data & Fetch Recommendations</h3>
        <p>Run the sample code below to sync your first products, record customer interactions, and request live recommendations:</p>

        <DocsCodeTabs examples={QUICKSTART_CURL} title="5-Minute Quickstart" />
      </section>

      <section id="next-steps">
        <h2>Next Steps</h2>
        <div className="docs-next-links">
          <Link to="/docs/authentication" className="docs-next-card">
            <span className="docs-next-kicker">Next Guide</span>
            <h4>Authentication & Key Scopes &rarr;</h4>
            <p>Learn how to manage scoped API keys, enforce permissions, and use session bearer tokens.</p>
          </Link>
          <Link to="/docs/reference" className="docs-next-card">
            <span className="docs-next-kicker">API Specs</span>
            <h4>API Reference &rarr;</h4>
            <p>Browse parameter tables, request body schemas, and response formats for all 85 endpoints.</p>
          </Link>
        </div>
      </section>
    </article>
  );
}
