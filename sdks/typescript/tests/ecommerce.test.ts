import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CatalogSync, EventBuilder, EventTracker, InputValidationError, RecommendationSession, deterministicId, type PreparedEvent, type Recommendations } from "../src/index.js";
import { apiError, client, mockFetch, type Call } from "./helpers.js";

const batchReply = (call: Call) => {
  const items = (call.body as { events: unknown[] }).events;
  return { body: { id: `batch-${items.length}`, status: "completed", accepted_count: items.length, duplicate_count: 0, rejected_count: 0, created_at: "" } };
};
const sentEvents = (calls: Call[]): PreparedEvent[] => calls.flatMap((c) => (c.body as { events: PreparedEvent[] }).events);
const flushMicrotasks = () => new Promise((r) => setTimeout(r, 0));

describe("EventBuilder", () => {
  const builder = new EventBuilder({ defaultContext: { channel: "web" } });

  it("shapes common interactions with merged context", () => {
    const view = builder.view("u1", "sku-1", { sessionId: "s1", context: { page: "pdp" } });
    expect(view).toMatchObject({ event_type: "view", user_id: "u1", external_product_id: "sku-1", context: { channel: "web", page: "pdp", session_id: "s1" } });
    expect(view.event_id).toMatch(/^evt_/);
    expect(builder.addToCart(null, "sku-1", { quantity: 2, price: 19.9, currency: "EUR" }).context).toEqual({ channel: "web", quantity: 2, price: "19.9", currency: "EUR" });
    expect(builder.removeFromCart("u1", "sku-1").context).toEqual({ channel: "web", quantity: 1 });
    expect(builder.rating("u1", "sku-1", 4).context).toEqual({ channel: "web", rating: 4, max_rating: 5 });
    expect(builder.search("u1", "linen shirt")).toMatchObject({ event_type: "search", external_product_id: null, context: { channel: "web", query: "linen shirt" } });
    expect(builder.addToWishlist("u1", "sku-1").event_type).toBe("add_to_wishlist");
    expect(builder.click("u1", "sku-1", { occurredAt: new Date("2026-01-01T00:00:00Z") }).occurred_at).toBe("2026-01-01T00:00:00.000Z");
  });

  it("derives replay-safe purchase ids from the order line, identical to the Python SDK", () => {
    const a = builder.purchase("u1", "sku-100", { orderId: "ORD-1001" });
    const b = builder.purchase("u1", "sku-100", { orderId: "ORD-1001", quantity: 3 });
    expect(a.event_id).toBe(b.event_id);
    expect(a.event_id).toBe("evt_512765915d2fb2861c182d11438721fcff2858a6"); // deterministic_id("purchase", "ORD-1001", "sku-100", prefix="evt")
    expect(a.context).toMatchObject({ order_id: "ORD-1001", quantity: 1 });
    const line = builder.purchase("u1", "sku-100", { orderId: "ORD-1", line: 1 });
    expect(line.event_id).toBe(deterministicId("purchase", "ORD-1", 1, { prefix: "evt" }));
    expect(builder.purchase("u1", "sku-100", { orderId: "ORD-1", eventId: "mine" }).event_id).toBe("mine");
    expect(builder.purchase("u1", "sku-100").event_id).toMatch(/^evt_[0-9a-f]{32}$/);
  });

  it("validates quantities and ratings", () => {
    expect(() => builder.addToCart("u1", "sku-1", { quantity: 0 })).toThrow(InputValidationError);
    expect(() => builder.purchase("u1", "sku-1", { quantity: 1.5 })).toThrow(InputValidationError);
    expect(() => builder.rating("u1", "sku-1", 6)).toThrow(InputValidationError);
    expect(() => builder.rating("u1", "sku-1", 8, { maxRating: 10 })).not.toThrow();
  });
});

describe("EventTracker", () => {
  it("flushes at batchSize in the background and the rest on close", async () => {
    const mock = mockFetch(batchReply);
    const tracker = new EventTracker(client(mock, { apiKey: "gr_live_x" }), { batchSize: 3 });
    tracker.view("u1", "sku-1");
    tracker.view("u1", "sku-2");
    expect(mock.calls).toHaveLength(0);
    tracker.addToCart("u1", "sku-2");
    await flushMicrotasks();
    expect(mock.calls).toHaveLength(1);
    expect(sentEvents(mock.calls).map((e) => e.event_type)).toEqual(["view", "view", "add_to_cart"]);
    tracker.purchase("u1", "sku-2", { orderId: "o1" });
    expect(tracker.pending).toBe(1);
    await tracker.close();
    expect(mock.calls).toHaveLength(2);
    expect(tracker.pending).toBe(0);
    expect(() => tracker.view("u1", "sku-3")).toThrow(/closed/);
  });

  it("flush() returns the merged result and concurrent flushes share one request", async () => {
    const mock = mockFetch(batchReply);
    const tracker = new EventTracker(client(mock, { apiKey: "gr_live_x" }));
    tracker.track({ event_type: "view", user_id: "u1" });
    tracker.custom("newsletter_signup", { userId: "u1" }, { list: "weekly" });
    const [a, b] = await Promise.all([tracker.flush(), tracker.flush()]);
    expect(a?.accepted_count).toBe(2);
    expect(b).toBe(a); // nothing was queued after the first flush started, so the second reports the same result
    expect(mock.calls).toHaveLength(1);
    expect(sentEvents(mock.calls)[1]).toMatchObject({ event_type: "newsletter_signup", context: { list: "weekly" } });
    expect(await tracker.flush()).toBeNull();
  });

  it("sends events queued while a flush is in flight (synchronous bursts lose nothing)", async () => {
    const mock = mockFetch(batchReply);
    const tracker = new EventTracker(client(mock, { apiKey: "gr_live_x" }), { batchSize: 25 });
    for (let i = 0; i < 144; i += 1) tracker.view(`u${i % 12}`, `sku-${i % 60}`); // no await between events
    await tracker.close();
    expect(sentEvents(mock.calls)).toHaveLength(144);
    expect(mock.calls.length).toBeGreaterThanOrEqual(2);
    for (const call of mock.calls) expect((call.body as { events: unknown[] }).events.length).toBeLessThanOrEqual(500);
    expect(new Set(sentEvents(mock.calls).map((e) => e.event_id)).size).toBe(144);
  });

  it("flush() waits for the in-flight request and then sends what arrived meanwhile", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const mock = mockFetch(async (call, i) => {
      if (i === 0) await gate;
      return batchReply(call);
    });
    const tracker = new EventTracker(client(mock, { apiKey: "gr_live_x" }));
    tracker.view("u1", "sku-1");
    const first = tracker.flush();
    tracker.view("u1", "sku-2");
    const second = tracker.flush();
    release();
    expect((await first)?.accepted_count).toBe(1);
    expect((await second)?.accepted_count).toBe(1);
    expect(sentEvents(mock.calls).map((e) => e.external_product_id)).toEqual(["sku-1", "sku-2"]);
  });

  it("re-queues failed events once without a handler, then drops them", async () => {
    const mock = mockFetch((call, i) => (i < 2 ? { status: 503, body: apiError("service_unavailable", "down", { retryable: false }) } : batchReply(call)));
    const tracker = new EventTracker(client(mock, { apiKey: "gr_live_x", retry: { maxRetries: 0 } }));
    tracker.view("u1", "sku-1");
    await expect(tracker.flush()).rejects.toThrow();
    expect(tracker.pending).toBe(1);
    expect(tracker.dropped).toBe(0);
    await expect(tracker.flush()).rejects.toThrow();
    expect(tracker.pending).toBe(0);
    expect(tracker.dropped).toBe(1);
    tracker.view("u1", "sku-2");
    expect((await tracker.flush())?.accepted_count).toBe(1);
  });

  it("hands failed events to onError and drops them", async () => {
    const mock = mockFetch({ status: 429, body: apiError("quota_exceeded") });
    const failures: PreparedEvent[][] = [];
    const tracker = new EventTracker(client(mock, { apiKey: "gr_live_x" }), { onError: (_e, events) => void failures.push(events) });
    tracker.view("u1", "sku-1");
    tracker.view("u1", "sku-2");
    expect(await tracker.flush()).toBeNull();
    expect(failures).toHaveLength(1);
    expect(failures[0]).toHaveLength(2);
    expect(tracker.pending).toBe(0);
  });

  it("bounds the queue and drops the oldest events", async () => {
    const mock = mockFetch(batchReply);
    const tracker = new EventTracker(client(mock, { apiKey: "gr_live_x" }), { batchSize: 100, maxQueueSize: 3 });
    for (let i = 0; i < 5; i += 1) tracker.view("u1", `sku-${i}`);
    expect(tracker.pending).toBe(3);
    expect(tracker.dropped).toBe(2);
    await tracker.close();
    expect(sentEvents(mock.calls).map((e) => e.external_product_id)).toEqual(["sku-2", "sku-3", "sku-4"]);
  });

  describe("with fake timers", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("flushes on the interval and stops the timer on close", async () => {
      const mock = mockFetch(batchReply);
      const tracker = new EventTracker(client(mock, { apiKey: "gr_live_x" }), { flushIntervalMs: 1000 });
      tracker.view("u1", "sku-1");
      await vi.advanceTimersByTimeAsync(999);
      expect(mock.calls).toHaveLength(0);
      await vi.advanceTimersByTimeAsync(2);
      expect(mock.calls).toHaveLength(1);
      await tracker.close();
      tracker.flush = () => Promise.reject(new Error("timer still running"));
      await vi.advanceTimersByTimeAsync(5000);
      expect(mock.calls).toHaveLength(1);
    });
  });

  it("supports `await using` disposal", async () => {
    const mock = mockFetch(batchReply);
    const tracker = new EventTracker(client(mock, { apiKey: "gr_live_x" }));
    tracker.view("u1", "sku-1");
    await tracker[Symbol.asyncDispose]();
    expect(mock.calls).toHaveLength(1);
  });

  it("rejects nonsense options", () => {
    const c = client(mockFetch({ body: {} }), { apiKey: "gr_live_x" });
    expect(() => new EventTracker(c, { batchSize: 0 })).toThrow(RangeError);
    expect(() => new EventTracker(c, { maxQueueSize: 0 })).toThrow(RangeError);
  });
});

describe("CatalogSync", () => {
  const product = (id: string, active = true) => ({ id, external_id: id, title: id, description: null, price: "1.00", category: null, is_active: active, availability_status: "available", metadata: {}, created_at: "", updated_at: "" });
  const server = (existing: ReturnType<typeof product>[], failDisable: string[] = []) => (call: Call) => {
    if (call.url.endsWith(":disable")) {
      const id = decodeURIComponent(call.url.split("/products/")[1].replace(":disable", ""));
      return failDisable.includes(id) ? { status: 409, body: apiError("state_conflict", "already disabled") } : { body: product(id, false) };
    }
    if (call.method === "GET") return { body: { items: existing, total: existing.length } };
    const items = (call.body as { products: unknown[] }).products;
    return { body: { accepted_count: items.length, created_count: 1, updated_count: items.length - 1, skipped_count: 0, rejected_count: 0, failures: [] } };
  };

  it("upserts the feed and disables active products that dropped out of it", async () => {
    const mock = mockFetch(server([product("keep"), product("gone"), product("already-off", false)]));
    const report = await new CatalogSync(client(mock, { apiKey: "gr_live_x" })).run([{ external_id: "keep", title: "Keep" }, { external_id: "new", title: "New" }], { disableMissing: true, idempotencyKey: "nightly-1" });
    expect(report.ok).toBe(true);
    expect(report.disabledIds).toEqual(["gone"]);
    expect(report.upsert.created_count).toBe(1);
    expect(report.summary()).toMatch(/^created=1 updated=1 rejected=0 disabled=1 disable_failures=0 requests=1 in \d+\.\ds$/);
    expect(mock.calls[0].headers["idempotency-key"]).toBe("nightly-1");
    expect(mock.calls.filter((c) => c.url.endsWith(":disable"))).toHaveLength(1);
  });

  it("does nothing beyond the upsert without disableMissing", async () => {
    const mock = mockFetch(server([product("gone")]));
    const report = await new CatalogSync(client(mock, { apiKey: "gr_live_x" })).run([{ external_id: "a", title: "A" }]);
    expect(report.disabledIds).toEqual([]);
    expect(mock.calls).toHaveLength(1);
  });

  it("refuses an empty feed with disableMissing unless allowEmpty", async () => {
    const mock = mockFetch(server([product("gone")]));
    const sync = new CatalogSync(client(mock, { apiKey: "gr_live_x" }));
    await expect(sync.run([], { disableMissing: true })).rejects.toBeInstanceOf(InputValidationError);
    expect(mock.calls).toHaveLength(0);
    const report = await sync.run([], { disableMissing: true, allowEmpty: true });
    expect(report.disabledIds).toEqual(["gone"]);
    expect(report.upsert.request_count).toBe(0);
  });

  it("validates rows before sending anything and collects disable failures", async () => {
    const mock = mockFetch(server([product("a"), product("stuck")], ["stuck"]));
    const sync = new CatalogSync(client(mock, { apiKey: "gr_live_x" }));
    await expect(sync.run([{ external_id: "a", title: "A" }, { external_id: "", title: "bad" }])).rejects.toBeInstanceOf(InputValidationError);
    expect(mock.calls).toHaveLength(0);
    const report = await sync.run([{ external_id: "a", title: "A" }], { disableMissing: true });
    expect(report.ok).toBe(false);
    expect(report.disableFailures).toEqual({ stuck: "already disabled" });
  });
});

describe("RecommendationSession", () => {
  const recs: Recommendations = { request_id: "rec-1", items: [{ external_product_id: "sku-1", position: 1 }, { external_product_id: "sku-2", position: 2 }], model_version_id: null, strategy: "personalized", fallback_used: false, fallback_tier: "none" };
  const server = (result: Recommendations) => (call: Call) => {
    if (call.url.includes("/recommendations")) return { body: result };
    const kind = call.url.split("/feedback/")[1];
    return { body: { event_id: `${kind}-${(call.body as { event_id: string }).event_id}`, feedback_type: kind, accepted: true, duplicate: false, received_at: "" } };
  };

  it("records the impression and links clicks to it", async () => {
    const mock = mockFetch(server(recs));
    const widget = new RecommendationSession(client(mock, { apiKey: "gr_live_x" }));
    const result = await widget.recommend({ userId: "u1", topN: 2, excludeProductIds: ["sku-9"] });
    expect(result.request_id).toBe("rec-1");
    expect(mock.calls.map((c) => c.url.replace("http://api.test", ""))).toEqual(["/v1/recommendations", "/v1/feedback/impressions"]);
    expect(mock.calls[0].body).toMatchObject({ user_id: "u1", top_n: 2, exclude_product_ids: ["sku-9"] });
    const impressionId = (mock.calls[1].body as { event_id: string }).event_id;
    await widget.click(result, "sku-2");
    expect(mock.calls[2].body).toMatchObject({ request_id: "rec-1", external_product_id: "sku-2", position: 2, impression_event_id: `impressions-${impressionId}` });
    await widget.convert(result, "sku-2", { value: "59.00" });
    expect(mock.calls[3].body).toMatchObject({ external_product_id: "sku-2", position: 2, value: "59.00" });
  });

  it("uses session recommendations when a sessionId is given", async () => {
    const mock = mockFetch(server(recs));
    await new RecommendationSession(client(mock, { apiKey: "gr_live_x" })).recommend({ sessionId: "s1", recentProductIds: ["sku-3"], topN: 4 });
    expect(mock.calls[0].url).toBe("http://api.test/v1/recommendations/session");
    expect(mock.calls[0].body).toEqual({ top_n: 4, context: { session_id: "s1", recent_product_ids: ["sku-3"] } });
  });

  it("skips the impression for empty results and when autoImpression is off", async () => {
    const empty = { ...recs, items: [], fallback_used: true, fallback_tier: "tenant_popular" };
    const mock = mockFetch(server(empty));
    await new RecommendationSession(client(mock, { apiKey: "gr_live_x" })).recommend({ userId: "u1" });
    expect(mock.calls).toHaveLength(1);
    const quiet = mockFetch(server(recs));
    const widget = new RecommendationSession(client(quiet, { apiKey: "gr_live_x" }), { autoImpression: false });
    const result = await widget.recommend({ userId: "u1" });
    expect(quiet.calls).toHaveLength(1);
    await widget.click(result, "sku-1");
    expect(quiet.calls[1].body).not.toHaveProperty("impression_event_id");
  });

  it("forgets the oldest impression links beyond `remember`", async () => {
    let n = 0;
    const mock = mockFetch((call) => server({ ...recs, request_id: call.url.includes("/recommendations") ? `rec-${(n += 1)}` : "" })(call));
    const widget = new RecommendationSession(client(mock, { apiKey: "gr_live_x" }), { remember: 1 });
    const first = await widget.recommend({ userId: "u1" });
    const second = await widget.recommend({ userId: "u1" });
    await widget.click(first, "sku-1");
    expect(mock.calls[4].body).not.toHaveProperty("impression_event_id");
    await widget.click(second, "sku-1");
    expect(mock.calls[5].body).toHaveProperty("impression_event_id");
  });
});
