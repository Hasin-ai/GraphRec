import { Link } from "react-router-dom";
import { DocsCodeTabs } from "../../docs/DocsCodeTabs";

export function DocsGuidesPage() {
  const eventCurl = `curl -X POST "https://api.graphrec.io/v1/events" \\
  -H "Authorization: ApiKey gr_live_YOUR_STOREFRONT_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": "usr_99182",
    "external_product_id": "SKU-4402",
    "event_type": "add_to_cart",
    "event_time": "2026-10-10T09:45:00.000Z",
    "properties": {
      "quantity": 1,
      "price": "59.00",
      "surface": "product_detail_page"
    }
  }'`;

  const sessionRecsCurl = `curl -X POST "https://api.graphrec.io/v1/recommendations/session" \\
  -H "Authorization: ApiKey gr_live_YOUR_STOREFRONT_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "recent_product_ids": ["SKU-100", "SKU-205", "SKU-310"],
    "top_n": 8,
    "fallback_allowed": true
  }'`;

  const retryPython = `from graphrec_sdk import GraphRec, RateLimitError, ServiceUnavailableError, APIConnectionError

# The SDK already retries 429s, retryable 503s and connection failures with
# backoff (max_retries, default 2). Only handle what is left after that.
client = GraphRec(api_key="gr_live_YOUR_STOREFRONT_KEY", max_retries=3)

def recommendations_or_empty(user_id: str) -> list[str]:
    try:
        recs = client.storefront.recommendations.get(
            user_id=user_id,
            top_n=10,
            fallback_allowed=True,   # the server serves popularity if the model can't
        )
        return [item.external_product_id for item in recs.items]
    except RateLimitError as exc:
        print("rate limited; retry after", exc.retry_after_seconds, "s")
    except (ServiceUnavailableError, APIConnectionError):
        pass
    return []   # render the shelf from your own bestsellers instead`;

  return (
    <div className="docs-page">
      <header className="docs-page-header">
        <div className="docs-breadcrumbs">
          <Link to="/docs">Docs</Link>
          <span className="separator">/</span>
          <span>Guides & Architecture</span>
        </div>
        <h1>Integration Guides & Architecture</h1>
        <p className="lead">
          In-depth architectural guides on interaction event telemetry, model selection, cold-start handling,
          and production reliability best practices.
        </p>
      </header>

      {/* 1. Event Ingestion */}
      <section id="event-ingestion" className="docs-section">
        <h2>1. Interaction Event Ingestion</h2>
        <p>
          GraphRec’s Dynamic Graph Sequential Recommender (DGSR) relies on high-fidelity user interaction sequences.
          Accurate telemetry is the foundation of high recommendation conversion.
        </p>

        <h3>Supported Event Types & Weights</h3>
        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr>
                <th>Event Type</th>
                <th>Graph Significance</th>
                <th>When to Trigger</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>view</code></td>
                <td>Exploration Intent (1.0x)</td>
                <td>Shopper views a product detail page (PDP) or expands a quick-look modal.</td>
              </tr>
              <tr>
                <td><code>click</code></td>
                <td>Attributed Interest (1.2x)</td>
                <td>Shopper clicks a recommended shelf card or search result link.</td>
              </tr>
              <tr>
                <td><code>add_to_wishlist</code></td>
                <td>Long-Term Interest (2.0x)</td>
                <td>Shopper saves an item to their favorites list or registry.</td>
              </tr>
              <tr>
                <td><code>add_to_cart</code></td>
                <td>High Purchase Intent (3.5x)</td>
                <td>Shopper adds an item to their shopping bag or cart.</td>
              </tr>
              <tr>
                <td><code>purchase</code></td>
                <td>Confirmed Preference (5.0x)</td>
                <td>Checkout completed; confirmed order items.</td>
              </tr>
              <tr>
                <td><code>rating</code></td>
                <td>Explicit Preference</td>
                <td>Shopper submits a 1-to-5 star rating or film review.</td>
              </tr>
            </tbody>
          </table>
        </div>

        <h3>Event Payload & Timestamps</h3>
        <p>
          Always send the client-observed ISO 8601 timestamp in <code>event_time</code> rather than relying on server receipt time.
          This ensures that offline events, mobile queues, or batched uploads preserve the authentic chronological sequence of the shopper's journey.
        </p>

        <DocsCodeTabs title="Sending an Event" curl={eventCurl} />
      </section>

      {/* 2. Recommendation Strategies */}
      <section id="recommendation-strategies" className="docs-section">
        <h2>2. Choosing the Right Recommendation Endpoint</h2>
        <p>
          GraphRec provides distinct recommendation algorithms tailored for different surfaces in your storefront:
        </p>

        <div className="docs-grid-2">
          <div className="docs-card">
            <h3>Personalized Recommendations</h3>
            <p><strong>Endpoint:</strong> <code>POST /v1/recommendations</code></p>
            <p>
              Uses the full historical DGSR dynamic graph model for authenticated customers with past activity.
              Captures evolving tastes, seasonal transitions, and multi-category preferences.
            </p>
            <span className="badge badge-success">For: Home page, For You shelves</span>
          </div>

          <div className="docs-card">
            <h3>Session-Based Recommendations</h3>
            <p><strong>Endpoint:</strong> <code>POST /v1/recommendations/session</code></p>
            <p>
              Passes the sequence of product IDs viewed in the shopper's current browsing session.
              Does not require a customer account. DGSR maps the session trajectory through item-transition embeddings.
            </p>
            <span className="badge badge-primary">For: Anonymous visitors, Cart upsells</span>
          </div>

          <div className="docs-card">
            <h3>Similar Items</h3>
            <p><strong>Endpoint:</strong> <code>POST /v1/recommendations/similar</code></p>
            <p>
              Calculates item-to-item cosine similarity within the latent DGSR graph representation space.
              Matches thematic, stylistic, and category affinity.
            </p>
            <span className="badge badge-neutral">For: PDP "More Like This" shelves</span>
          </div>

          <div className="docs-card">
            <h3>Popular Fallback</h3>
            <p><strong>Endpoint:</strong> <code>POST /v1/recommendations/popular</code></p>
            <p>
              Returns top trending and highest-velocity items across the tenant catalog over a rolling window.
              Provides guaranteed sub-5ms response times.
            </p>
            <span className="badge badge-warning">For: Cold start, Failover fallback</span>
          </div>
        </div>

        <h3>Session Recommendations Example</h3>
        <DocsCodeTabs title="Session Recommendations Request" curl={sessionRecsCurl} />
      </section>

      {/* 3. Cold-Start Handling */}
      <section id="cold-start" className="docs-section">
        <h2>3. Cold-Start Handling & Fallbacks</h2>
        <p>
          E-commerce storefronts regularly encounter two distinct cold-start challenges:
        </p>

        <h3>Cold Shoppers (New Visitors)</h3>
        <p>
          When a shopper has zero historical interactions:
        </p>
        <ol>
          <li>
            <strong>First 1-2 Clicks:</strong> Use <code>POST /v1/recommendations/session</code> as soon as the visitor clicks their first product.
            DGSR adapts to immediate intent within a single session without requiring account login.
          </li>
          <li>
            <strong>Zero Clicks:</strong> By default, setting <code>fallback_allowed: true</code> causes <code>/v1/recommendations</code> to
            smoothly degrade to category-weighted popular items, ensuring your UI never renders an empty shelf.
          </li>
        </ol>

        <h3>Cold Items (New Catalog SKUs)</h3>
        <p>
          When you upload new products that haven't accrued views or purchases yet:
        </p>
        <ul>
          <li>
            GraphRec projects new items into graph embedding space using category hierarchies, tags, and brand metadata.
          </li>
          <li>
            New items are eligible for similarity shelves immediately upon synchronization via <code>CatalogSync</code>.
          </li>
        </ul>
      </section>

      {/* 4. Retries & Observability */}
      <section id="retries-errors" className="docs-section">
        <h2>4. Retries, Observability & Circuit Breaking</h2>
        <p>
          Storefront page rendering must never block or crash if an upstream ML model experiences high load or restarts.
        </p>

        <h3>Resilience Checklist</h3>
        <ul>
          <li><strong>Set strict timeouts:</strong> Configure <code>timeout=0.3</code> (300ms) for storefront recommendation requests.</li>
          <li><strong>Enable automatic fallback:</strong> Always pass <code>fallback_allowed: true</code> so the API serves trending backups if the neural model is warming up.</li>
          <li><strong>Exponential backoff:</strong> Only retry idempotent GET requests or batch uploads on 429 and 503.</li>
        </ul>

        <DocsCodeTabs title="Graceful Fallback Implementation" python={retryPython} />
      </section>
    </div>
  );
}
