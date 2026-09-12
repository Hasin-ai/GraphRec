/**
 * Storefront integration in ~40 lines: catalog, events, recommendations, feedback.
 *
 *   export GRAPHREC_BASE_URL=http://localhost:8010
 *   export GRAPHREC_API_KEY=gr_live_...        # scopes: STOREFRONT_KEY_SCOPES
 *   npm run build && node examples/storefront-quickstart.ts
 */
import { GraphRec, NotFoundError, type ProductInput } from "@graphrec/sdk";
import { EventTracker, RecommendationSession } from "@graphrec/sdk/ecommerce";

const CATALOG: ProductInput[] = [
  { external_id: "sku-100", title: "Linen shirt", price: "49.90", category: "shirts", metadata: { brand: "Acme", color: "white" } },
  { external_id: "sku-101", title: "Chino trousers", price: "59.00", category: "trousers", metadata: { brand: "Acme" } },
  { external_id: "sku-102", title: "Canvas sneakers", price: "79.00", category: "shoes", metadata: { brand: "Stride" } },
];

async function main(): Promise<void> {
  const client = new GraphRec(); // reads GRAPHREC_BASE_URL and GRAPHREC_API_KEY
  console.log("API health:", await client.health());

  // 1. Keep the catalog in sync (split automatically to respect the 16 KiB body limit).
  const result = await client.products.bulkUpsert(CATALOG);
  console.log(`catalog: created=${result.created_count} updated=${result.updated_count}`);

  // 2. Record what shoppers do. Events are buffered and sent in batches.
  const tracker = new EventTracker(client, { batchSize: 50 });
  tracker.view("customer-42", "sku-100", { sessionId: "sess-1" });
  tracker.addToCart("customer-42", "sku-100", { quantity: 1, price: "49.90" });
  tracker.purchase("customer-42", "sku-100", { orderId: "ORD-1001", price: "49.90" });
  await tracker.close();

  // 3. Show recommendations on the product page and report what happened.
  const widget = new RecommendationSession(client);
  const recs = await widget.recommend({ userId: "customer-42", topN: 4, excludeProductIds: ["sku-100"] });
  const productIds = recs.items.map((i) => i.external_product_id);
  console.log(`strategy=${recs.strategy} fallback=${recs.fallback_used} items=${JSON.stringify(productIds)}`);
  if (recs.items.length) {
    const clicked = recs.items[0].external_product_id;
    await widget.click(recs, clicked);
    await widget.convert(recs, clicked, { value: "59.00" });
  }

  try {
    await client.products.get("does-not-exist");
  } catch (error) {
    if (!(error instanceof NotFoundError)) throw error;
    console.log("expected 404, correlation id:", error.correlationId);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
