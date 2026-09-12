/**
 * The SDK inside a storefront backend, using only `node:http` (the same shape
 * works in Express, Fastify, Hono or Next.js route handlers).
 *
 *   GRAPHREC_API_KEY=gr_live_... npm run build && node examples/http-storefront.ts
 *   curl -H 'X-Customer-Id: customer-42' http://localhost:3000/products/sku-100
 *   curl -X POST -d '{"sku":"sku-100","quantity":2}' -H 'Cookie: sid=abc' http://localhost:3000/cart
 *
 * The key needs STOREFRONT_KEY_SCOPES.
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { APIError, GraphRec } from "@graphrec/sdk";
import { EventTracker, RecommendationSession } from "@graphrec/sdk/ecommerce";

const client = new GraphRec({ timeoutMs: 2_000, retry: { maxRetries: 1 } }); // keep page latency bounded
const tracker = new EventTracker(client, { batchSize: 200, flushIntervalMs: 2_000, onError: (error) => console.warn("event flush failed:", error) });
const recs = new RecommendationSession(client);

function shopper(request: IncomingMessage): { userId: string | null; sessionId: string | undefined } {
  const header = request.headers["x-customer-id"];
  const cookie = request.headers.cookie?.match(/(?:^|;\s*)sid=([^;]+)/)?.[1];
  return { userId: typeof header === "string" && header ? header : null, sessionId: cookie };
}

function readJson(request: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    let body = "";
    request.on("data", (chunk: Buffer) => (body += chunk.toString("utf8")));
    request.on("end", () => {
      try {
        resolve(body ? (JSON.parse(body) as Record<string, unknown>) : {});
      } catch (error) {
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

function send(response: ServerResponse, status: number, payload: unknown): void {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(payload));
}

async function productPage(sku: string, request: IncomingMessage, response: ServerResponse): Promise<void> {
  const who = shopper(request);
  tracker.view(who.userId, sku, { sessionId: who.sessionId });
  let related: string[] = [];
  let requestId: string | null = null;
  try {
    const result = who.userId
      ? await recs.recommend({ userId: who.userId, topN: 6, excludeProductIds: [sku] })
      : await recs.recommend({ sessionId: who.sessionId ?? "anonymous", recentProductIds: [sku], topN: 6 });
    related = result.items.map((i) => i.external_product_id);
    requestId = result.request_id;
  } catch (error) {
    if (!(error instanceof APIError)) throw error; // never break the page because recommendations failed
  }
  send(response, 200, { sku, related, recommendation_request_id: requestId });
}

async function addToCart(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const who = shopper(request);
  const payload = await readJson(request);
  if (typeof payload.sku !== "string") return send(response, 422, { error: "sku is required" });
  tracker.addToCart(who.userId, payload.sku, { quantity: Number(payload.quantity ?? 1), sessionId: who.sessionId });
  send(response, 200, { status: "ok" });
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://localhost");
  const product = url.pathname.match(/^\/products\/([^/]+)$/);
  const handler = product && request.method === "GET" ? productPage(decodeURIComponent(product[1]), request, response) : url.pathname === "/cart" && request.method === "POST" ? addToCart(request, response) : null;
  if (!handler) return send(response, 404, { error: "not found" });
  handler.catch((error) => {
    console.error(error);
    send(response, 500, { error: "internal error" });
  });
});

server.listen(3000, () => console.log("storefront listening on http://localhost:3000"));

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    server.close();
    tracker.close().finally(() => process.exit(0)); // send the buffered events before exiting
  });
}
