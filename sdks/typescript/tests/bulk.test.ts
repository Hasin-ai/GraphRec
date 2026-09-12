import { describe, expect, it } from "vitest";
import { APIError, DEFAULT_MAX_BODY_BYTES, InputValidationError, PayloadTooLargeError, chunkItems, type ProductInput } from "../src/index.js";
import { apiError, client, mockFetch, type Call } from "./helpers.js";

const byteLength = (value: unknown) => Buffer.byteLength(JSON.stringify(value), "utf8");
const products = (n: number, pad = 0): ProductInput[] => Array.from({ length: n }, (_, i) => ({ external_id: `sku-${i}`, title: `Product ${i}`, price: "10.00", metadata: pad ? { blob: "x".repeat(pad) } : {} }));
const bulkReply = (call: Call) => {
  const items = (call.body as { products: unknown[] }).products;
  return { body: { accepted_count: items.length, created_count: items.length, updated_count: 0, skipped_count: 0, rejected_count: 0, failures: [] } };
};
const batchReply = (call: Call) => {
  const items = (call.body as { events: unknown[] }).events;
  return { body: { id: `batch-${items.length}`, status: "completed", accepted_count: items.length, duplicate_count: 0, rejected_count: 0, created_at: "" } };
};

describe("chunkItems", () => {
  it("keeps every request within the byte budget and preserves order", () => {
    const items = products(300, 40);
    const chunks = chunkItems(items, { envelopeKey: "products", maxBytes: 4096, maxItems: 500 });
    expect(chunks.length).toBeGreaterThan(1);
    for (const chunk of chunks) expect(byteLength({ products: chunk })).toBeLessThanOrEqual(4096);
    expect(chunks.flat()).toEqual(items);
  });

  it("fills chunks greedily: adding the next item would overflow", () => {
    const items = products(100, 40);
    const chunks = chunkItems(items, { envelopeKey: "products", maxBytes: 2048, maxItems: 500 });
    for (let i = 0; i < chunks.length - 1; i += 1) {
      expect(byteLength({ products: [...chunks[i], chunks[i + 1][0]] })).toBeGreaterThan(2048);
    }
  });

  it("respects the item cap independently of the byte budget", () => {
    const chunks = chunkItems(products(10), { envelopeKey: "products", maxBytes: 1_000_000, maxItems: 4 });
    expect(chunks.map((c) => c.length)).toEqual([4, 4, 2]);
  });

  it("rejects an item that cannot fit a request on its own, naming it", () => {
    expect(() => chunkItems(products(1, 5000), { envelopeKey: "products", maxBytes: 4096, maxItems: 10, describe: "Product" })).toThrow(/Product "sku-0" encodes to \d+ bytes/);
    expect(() => chunkItems([{ event_id: "e1", context: { x: "y".repeat(200) } }], { envelopeKey: "events", maxBytes: 100, maxItems: 10 })).toThrow(InputValidationError);
  });

  it("measures multi-byte characters as bytes, not code units", () => {
    const items = [{ external_id: "a", title: "é".repeat(30) }];
    expect(chunkItems(items, { envelopeKey: "products", maxBytes: 200, maxItems: 10 })).toHaveLength(1);
    expect(() => chunkItems(items, { envelopeKey: "products", maxBytes: 80, maxItems: 10 })).toThrow(InputValidationError);
  });

  it("returns no chunks for no items", () => {
    expect(chunkItems([], { envelopeKey: "products", maxBytes: 100, maxItems: 10 })).toEqual([]);
  });
});

describe("products.bulkUpsert", () => {
  it("splits on the default 16 KiB budget and sums the counts", async () => {
    const mock = mockFetch(bulkReply);
    const result = await client(mock, { apiKey: "gr_live_x" }).products.bulkUpsert(products(400));
    expect(mock.calls.length).toBeGreaterThan(1);
    for (const call of mock.calls) expect(Buffer.byteLength(call.rawBody as string, "utf8")).toBeLessThanOrEqual(DEFAULT_MAX_BODY_BYTES);
    expect(result.accepted_count).toBe(400);
    expect(result.created_count).toBe(400);
    expect(result.request_count).toBe(mock.calls.length);
    expect(result.failures).toEqual([]);
  });

  it("derives per-chunk Idempotency-Keys from the caller's key", async () => {
    const mock = mockFetch(bulkReply);
    const c = client(mock, { apiKey: "gr_live_x", maxBatchItems: 3 });
    await c.products.bulkUpsert(products(7), { idempotencyKey: "sync-42" });
    expect(mock.calls.map((call) => call.headers["idempotency-key"])).toEqual(["sync-42:1/3", "sync-42:2/3", "sync-42:3/3"]);
    await c.products.bulkUpsert(products(2), { idempotencyKey: "single" });
    expect(mock.calls[3].headers["idempotency-key"]).toBe("single");
    await c.products.bulkUpsert(products(2));
    expect(mock.calls[4].headers["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("honours custom maxBodyBytes and maxBatchItems", async () => {
    const mock = mockFetch(bulkReply);
    await client(mock, { apiKey: "gr_live_x", maxBodyBytes: 1024, maxBatchItems: 5 }).products.bulkUpsert(products(20));
    expect(mock.calls.length).toBeGreaterThanOrEqual(4);
    for (const call of mock.calls) {
      expect(Buffer.byteLength(call.rawBody as string, "utf8")).toBeLessThanOrEqual(1024);
      expect((call.body as { products: unknown[] }).products.length).toBeLessThanOrEqual(5);
    }
  });

  it("rejects later duplicates locally, like the server, and still sends the rest", async () => {
    const mock = mockFetch(bulkReply);
    const result = await client(mock, { apiKey: "gr_live_x" }).products.bulkUpsert([...products(3), { external_id: "sku-1", title: "again" }]);
    expect((mock.calls[0].body as { products: unknown[] }).products).toHaveLength(3);
    expect(result.accepted_count).toBe(3);
    expect(result.rejected_count).toBe(1);
    expect(result.failures).toEqual([{ external_id: "sku-1", reason: "Duplicate item external_id within batch" }]);
  });

  it("refuses an oversized product or an empty input before sending", async () => {
    const mock = mockFetch(bulkReply);
    const c = client(mock, { apiKey: "gr_live_x" });
    await expect(c.products.bulkUpsert(products(1, 20_000))).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.products.bulkUpsert([])).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.products.bulkUpsert([{ external_id: "a", title: "" }])).rejects.toBeInstanceOf(InputValidationError);
    expect(mock.calls).toHaveLength(0);
  });

  it("attaches the partial result when a later request fails", async () => {
    const mock = mockFetch((call, i) => (i === 1 ? { status: 413, body: apiError("payload_too_large") } : bulkReply(call)));
    const error = await client(mock, { apiKey: "gr_live_x", maxBatchItems: 4 })
      .products.bulkUpsert([...products(10), { external_id: "sku-0", title: "dup" }])
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PayloadTooLargeError);
    const partial = (error as APIError).partialResult as { accepted_count: number; request_count: number; rejected_count: number };
    expect(partial.accepted_count).toBe(4);
    expect(partial.request_count).toBe(1);
    expect(partial.rejected_count).toBe(1); // the local duplicate is reported too
    expect(mock.calls).toHaveLength(2);
  });

  it("merges server-side failures across requests", async () => {
    const mock = mockFetch((call) => {
      const reply = bulkReply(call);
      reply.body.failures = [{ external_id: "bad", reason: "invalid" }] as never;
      reply.body.rejected_count = 1;
      return reply;
    });
    const result = await client(mock, { apiKey: "gr_live_x", maxBatchItems: 2 }).products.bulkUpsert(products(4));
    expect(result.rejected_count).toBe(2);
    expect(result.failures).toHaveLength(2);
  });
});

describe("events.createBatch", () => {
  it("chunks, sums and returns every server batch", async () => {
    const mock = mockFetch(batchReply);
    const events = Array.from({ length: 500 }, (_, i) => ({ event_type: "view", user_id: `u${i % 10}`, external_product_id: `sku-${i}`, context: { referrer: "https://example.com/" + "p".repeat(40) } }));
    const result = await client(mock, { apiKey: "gr_live_x" }).events.createBatch(events);
    expect(mock.calls.length).toBeGreaterThan(1);
    for (const call of mock.calls) expect(Buffer.byteLength(call.rawBody as string, "utf8")).toBeLessThanOrEqual(DEFAULT_MAX_BODY_BYTES);
    expect(result.accepted_count).toBe(500);
    expect(result.request_count).toBe(mock.calls.length);
    expect(result.batches).toHaveLength(mock.calls.length);
    expect(mock.calls[0].headers["idempotency-key"]).toBeUndefined(); // events dedupe by event_id instead
  });

  it("assigns ids before chunking so a retry re-sends the same events", async () => {
    const mock = mockFetch(batchReply);
    await client(mock, { apiKey: "gr_live_x" }).events.createBatch([{ event_type: "view" }, { event_type: "click", event_id: "mine" }]);
    const sent = (mock.calls[0].body as { events: { event_id: string }[] }).events;
    expect(sent[0].event_id).toMatch(/^evt_/);
    expect(sent[1].event_id).toBe("mine");
  });

  it("attaches the partial result on failure and rejects empty input", async () => {
    const mock = mockFetch((call, i) => (i === 1 ? { status: 503, body: apiError("service_unavailable", "down", { retryable: false }) } : batchReply(call)));
    const c = client(mock, { apiKey: "gr_live_x", maxBatchItems: 2, retry: { maxRetries: 0 } });
    const error = await c.events.createBatch(Array.from({ length: 5 }, () => ({ event_type: "view" }))).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(APIError);
    expect((error as APIError).partialResult).toMatchObject({ accepted_count: 2, request_count: 1 });
    await expect(c.events.createBatch([])).rejects.toBeInstanceOf(InputValidationError);
  });
});
