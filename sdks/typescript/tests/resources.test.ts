import { describe, expect, it } from "vitest";
import {
  AuthenticationError,
  InputValidationError,
  NotFoundError,
  STOREFRONT_KEY_SCOPES,
  StateConflictError,
  WaitTimeoutError,
  positionOf,
  type Recommendations,
} from "../src/index.js";
import { TOKEN, apiError, client, mockFetch, type Call } from "./helpers.js";

const last = (calls: Call[]) => calls[calls.length - 1];
const UUID = "3f0e2b8e-9c1d-4c1e-8e2a-000000000001";

describe("tenants & auth", () => {
  it("registers with a generated Idempotency-Key and normalises the email", async () => {
    const mock = mockFetch({ status: 201, body: { id: UUID, name: "Acme", status: "active", setup_token: "tok", setup_token_expires_at: null } });
    const tenant = await client(mock).tenants.register({ name: " Acme ", admin_email: "Owner@Acme.Example" });
    const call = mock.calls[0];
    expect(call.method).toBe("POST");
    expect(call.url).toBe("http://api.test/v1/tenants");
    expect(call.body).toEqual({ name: "Acme", admin_email: "owner@acme.example" });
    expect(call.headers["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(call.headers.authorization).toBeUndefined();
    expect(tenant.replayed).toBe(false);
    expect(tenant.setup_token).toBe("tok");
  });

  it("reuses a caller-supplied Idempotency-Key", async () => {
    const mock = mockFetch({ status: 201, body: { id: UUID } });
    await client(mock).tenants.register({ name: "Acme", admin_email: "a@b.c" }, { idempotencyKey: "key-1" });
    expect(mock.calls[0].headers["idempotency-key"]).toBe("key-1");
  });

  it("validates registration input locally", async () => {
    const mock = mockFetch({ body: {} });
    await expect(client(mock).tenants.register({ name: "", admin_email: "a@b.c" })).rejects.toBeInstanceOf(InputValidationError);
    await expect(client(mock).tenants.register({ name: "x", admin_email: "nope" })).rejects.toBeInstanceOf(InputValidationError);
    expect(mock.calls).toHaveLength(0);
  });

  it("sets up a password with the one-time token and surfaces invalid_setup_token", async () => {
    const mock = mockFetch([{ body: TOKEN }, { status: 401, body: apiError("invalid_setup_token", "Invalid or expired setup token") }]);
    const c = client(mock);
    const token = await c.auth.setupPassword({ setupToken: "t".repeat(43), password: "long-password", email: "A@B.C" });
    expect(token.access_token).toBe("h.p.s");
    expect(mock.calls[0].body).toEqual({ setup_token: "t".repeat(43), password: "long-password", email: "a@b.c" });
    const err = await c.auth.setupPassword({ setupToken: "t".repeat(43), password: "long-password" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(AuthenticationError);
    expect((err as AuthenticationError).code).toBe("invalid_setup_token");
    expect(mock.calls[1].body).not.toHaveProperty("email");
  });

  it("rejects short setup tokens and passwords before sending", async () => {
    const mock = mockFetch({ body: TOKEN });
    await expect(client(mock).auth.setupPassword({ setupToken: "short", password: "long-password" })).rejects.toBeInstanceOf(InputValidationError);
    await expect(client(mock).auth.setupPassword({ setupToken: "t".repeat(43), password: "short" })).rejects.toBeInstanceOf(InputValidationError);
    expect(mock.calls).toHaveLength(0);
  });
});

describe("api keys", () => {
  const key = { id: UUID, name: "web", prefix: "gr_live_abc", scopes: ["catalog:read"], status: "active", expires_at: null, created_at: "2026-01-01T00:00:00Z", last_used_at: null, revoked_at: null, grace_expires_at: null };

  it("creates a key with de-duplicated scopes and a relative expiry", async () => {
    const mock = mockFetch({ status: 201, body: { ...key, secret: "gr_live_secret" } });
    const before = Date.now();
    const created = await client(mock, { accessToken: "tok" }).apiKeys.create({ name: " web ", scopes: [...STOREFRONT_KEY_SCOPES, "catalog:read"], expiresInDays: 30 });
    const body = mock.calls[0].body as { name: string; scopes: string[]; expires_at: string };
    expect(body.name).toBe("web");
    expect(body.scopes).toEqual([...STOREFRONT_KEY_SCOPES]);
    expect(new Date(body.expires_at).getTime()).toBeGreaterThanOrEqual(before + 30 * 86_400_000 - 1000);
    expect(created.secret).toBe("gr_live_secret");
  });

  it("sends an absolute expiry or null", async () => {
    const mock = mockFetch({ status: 201, body: { ...key, secret: "s" } });
    const c = client(mock, { accessToken: "tok" });
    await c.apiKeys.create({ name: "a", scopes: ["catalog:read"], expiresAt: new Date("2027-01-01T00:00:00Z") });
    await c.apiKeys.create({ name: "b", scopes: ["catalog:read"] });
    expect((mock.calls[0].body as { expires_at: string }).expires_at).toBe("2027-01-01T00:00:00.000Z");
    expect((mock.calls[1].body as { expires_at: null }).expires_at).toBeNull();
  });

  it("validates names, scopes, reasons and grace periods", async () => {
    const mock = mockFetch({ body: key });
    const c = client(mock, { accessToken: "tok" });
    await expect(c.apiKeys.create({ name: "", scopes: ["catalog:read"] })).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.apiKeys.create({ name: "x", scopes: [] })).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.apiKeys.create({ name: "x", scopes: ["catalog:read"], expiresInDays: 0 })).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.apiKeys.rotate(UUID, { reason: "" })).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.apiKeys.rotate(UUID, { reason: "r", gracePeriodSeconds: 90_000 })).rejects.toBeInstanceOf(InputValidationError);
    expect(mock.calls).toHaveLength(0);
  });

  it("rotates, lists, gets and revokes", async () => {
    const mock = mockFetch({ body: { ...key, secret: "new" } });
    const c = client(mock, { accessToken: "tok" });
    await c.apiKeys.rotate(UUID, { reason: "leaked" });
    expect(last(mock.calls).url).toBe(`http://api.test/v1/api-keys/${UUID}/rotate`);
    expect(last(mock.calls).body).toEqual({ reason: "leaked", grace_period_seconds: 3600 });
    await c.apiKeys.list();
    expect(last(mock.calls).method).toBe("GET");
    await c.apiKeys.get(UUID);
    expect(last(mock.calls).url).toBe(`http://api.test/v1/api-keys/${UUID}`);
    await c.apiKeys.revoke(UUID);
    expect(last(mock.calls).method).toBe("DELETE");
    expect(last(mock.calls).rawBody).toBeUndefined();
  });
});

describe("billing", () => {
  it("reads the subscription and picks a usage dimension", async () => {
    const usage = { period_start: "", period_end: "", reset_at: "", last_reconciled_at: "", project_defaults: false, dimensions: [{ type: "accepted_events", used: 5, limit: 100, remaining: 95, unit: "count" }] };
    const mock = mockFetch((call) => ({ body: call.url.endsWith("/usage") ? usage : { plan_code: "starter", limits: {} } }));
    const c = client(mock, { apiKey: "gr_live_x" });
    expect((await c.subscription.get()).plan_code).toBe("starter");
    expect((await c.usage.dimension("accepted_events"))?.remaining).toBe(95);
    expect(await c.usage.dimension("training_jobs")).toBeUndefined();
  });
});

describe("products", () => {
  const product = { id: UUID, external_id: "sku-1", title: "Shirt", description: null, price: "10.00", category: "shirts", is_active: true, availability_status: "available", metadata: { brand: "Acme" }, created_at: "", updated_at: "" };

  it("upserts one product with money as a string and encodes the path", async () => {
    const mock = mockFetch({ body: product });
    await client(mock, { apiKey: "gr_live_x" }).products.upsert({ external_id: "sku/1 a", title: "Shirt", price: 10, metadata: { brand: "Acme" } });
    expect(mock.calls[0].method).toBe("PUT");
    expect(mock.calls[0].url).toBe("http://api.test/v1/products/sku%2F1%20a");
    expect(mock.calls[0].body).toEqual({ external_id: "sku/1 a", title: "Shirt", price: "10", metadata: { brand: "Acme" } });
  });

  it("update() reads the current product, merges changes and PATCHes the whole record", async () => {
    const mock = mockFetch((call) => ({ body: call.method === "PATCH" ? { ...product, price: "9.99" } : product }));
    const updated = await client(mock, { apiKey: "gr_live_x" }).products.update("sku-1", { price: "9.99", category: undefined });
    expect(mock.calls.map((c) => c.method)).toEqual(["GET", "PATCH"]);
    expect(mock.calls[1].body).toEqual({ external_id: "sku-1", title: "Shirt", description: null, price: "9.99", category: "shirts", is_active: true, availability_status: "available", metadata: { brand: "Acme" } });
    expect(updated.price).toBe("9.99");
  });

  it("update() with nothing to change is rejected before any request", async () => {
    const mock = mockFetch({ body: product });
    await expect(client(mock, { apiKey: "gr_live_x" }).products.update("sku-1", {})).rejects.toBeInstanceOf(InputValidationError);
    expect(mock.calls).toHaveLength(0);
  });

  it("validates product fields", async () => {
    const mock = mockFetch({ body: product });
    const c = client(mock, { apiKey: "gr_live_x" });
    await expect(c.products.upsert({ external_id: "", title: "x" })).rejects.toThrow(/external_id/);
    await expect(c.products.upsert({ external_id: "a", title: "" })).rejects.toThrow(/title/);
    await expect(c.products.upsert({ external_id: "a", title: "x", price: -1 })).rejects.toThrow(/price/);
    await expect(c.products.upsert({ external_id: "a", title: "x", price: "abc" })).rejects.toThrow(/price/);
    await expect(c.products.upsert({ external_id: "a", title: "x", category: "c".repeat(101) })).rejects.toThrow(/category/);
    await expect(c.products.upsert({ external_id: "a", title: "x", metadata: [] as unknown as Record<string, unknown> })).rejects.toThrow(/metadata/);
    expect(mock.calls).toHaveLength(0);
  });

  it("lists, gets, disables and maps 404", async () => {
    const mock = mockFetch((call) => (call.url.endsWith("/missing") ? { status: 404, body: apiError("resource_not_found") } : { body: call.url.endsWith("/products") ? { items: [product], total: 1 } : product }));
    const c = client(mock, { apiKey: "gr_live_x" });
    expect((await c.products.list()).total).toBe(1);
    expect((await c.products.get("sku-1")).external_id).toBe("sku-1");
    await c.products.disable("sku-1");
    expect(last(mock.calls).url).toBe("http://api.test/v1/products/sku-1:disable");
    expect(last(mock.calls).method).toBe("POST");
    expect(last(mock.calls).rawBody).toBeUndefined();
    expect(last(mock.calls).headers["content-type"]).toBeUndefined();
    await expect(c.products.get("missing")).rejects.toBeInstanceOf(NotFoundError);
  });
});

describe("events", () => {
  it("creates one event with a generated id, ISO timestamp and duplicate receipt", async () => {
    const mock = mockFetch({ body: { event_id: "evt_x", accepted: true, duplicate: true, received_at: "" } });
    const receipt = await client(mock, { apiKey: "gr_live_x" }).events.create({ event_type: "view", user_id: "u1", external_product_id: "sku-1", occurred_at: new Date("2026-01-01T00:00:00Z") });
    const body = mock.calls[0].body as Record<string, unknown>;
    expect(body.event_id).toMatch(/^evt_[0-9a-f]{32}$/);
    expect(body).toMatchObject({ event_type: "view", user_id: "u1", external_product_id: "sku-1", context: {}, occurred_at: "2026-01-01T00:00:00.000Z" });
    expect(receipt.duplicate).toBe(true);
  });

  it("keeps a caller-supplied event id and validates shape", async () => {
    const mock = mockFetch({ body: {} });
    const c = client(mock, { apiKey: "gr_live_x" });
    await c.events.create({ event_id: "order-1", event_type: "purchase" });
    expect((mock.calls[0].body as { event_id: string }).event_id).toBe("order-1");
    await expect(c.events.create({ event_type: "" })).rejects.toThrow(/event_type/);
    await expect(c.events.create({ event_type: "view", event_id: "x".repeat(101) })).rejects.toThrow(/event_id/);
    await expect(c.events.create({ event_type: "view", occurred_at: "not a date" })).rejects.toThrow(/occurred_at/);
    await expect(c.events.create({ event_type: "view", context: [] as unknown as Record<string, unknown> })).rejects.toThrow(/context/);
  });

  it("lists and gets batches", async () => {
    const batch = { id: UUID, status: "completed", accepted_count: 2, duplicate_count: 0, rejected_count: 0, created_at: "" };
    const mock = mockFetch((call) => ({ body: call.url.endsWith("/batches") ? [batch] : batch }));
    const c = client(mock, { apiKey: "gr_live_x" });
    expect(await c.events.listBatches()).toHaveLength(1);
    expect((await c.events.getBatch(UUID)).id).toBe(UUID);
    expect(last(mock.calls).url).toBe(`http://api.test/v1/events/batches/${UUID}`);
  });
});

describe("datasets", () => {
  const snapshot = { id: UUID, tenant_id: UUID, training_job_id: null, cutoff_at: "", event_count: 1, product_count: 1, user_count: 1, artifact_uri: "", checksum: "abc", created_at: "" };

  it("uploads a CSV string as multipart without a JSON content type", async () => {
    const mock = mockFetch({ body: { accepted_events: 1, accepted_products: 0, dataset_snapshot: snapshot } });
    const result = await client(mock, { apiKey: "gr_live_x" }).datasets.upload("event_id,event_type\na,view\n", { filename: "events.csv" });
    const call = mock.calls[0];
    expect(call.url).toBe("http://api.test/v1/datasets/upload");
    expect(call.headers["content-type"]).toBeUndefined(); // fetch sets the multipart boundary itself
    const form = call.rawBody as FormData;
    const file = form.get("file") as File;
    expect(file.name).toBe("events.csv");
    expect(file.type).toBe("text/csv");
    expect(await file.text()).toContain("a,view");
    expect(result.accepted_events).toBe(1);
  });

  it("guesses JSON from the content and accepts bytes and Blobs", async () => {
    const mock = mockFetch({ body: { accepted_events: 0, accepted_products: 1, dataset_snapshot: snapshot } });
    const c = client(mock, { apiKey: "gr_live_x" });
    await c.datasets.upload('{"products": []}');
    await c.datasets.upload(new TextEncoder().encode("[]"));
    await c.datasets.upload(new File(["x,y"], "my.csv", { type: "text/csv" }));
    const files = mock.calls.map((call) => (call.rawBody as FormData).get("file") as File);
    expect(files[0].type).toBe("application/json");
    expect(files[0].name).toBe("dataset.json");
    expect(files[1].type).toBe("application/json");
    expect(files[2].name).toBe("my.csv");
  });

  it("rejects an empty dataset", async () => {
    const mock = mockFetch({ body: {} });
    await expect(client(mock, { apiKey: "gr_live_x" }).datasets.upload("")).rejects.toBeInstanceOf(InputValidationError);
    expect(mock.calls).toHaveLength(0);
  });

  it("creates, lists and reads snapshots", async () => {
    const mock = mockFetch((call) => ({ body: call.url.endsWith("/snapshots") && call.method === "GET" ? { items: [snapshot] } : snapshot }));
    const c = client(mock, { apiKey: "gr_live_x" });
    await c.datasets.createSnapshot({ cutoffAt: new Date("2026-02-01T00:00:00Z"), description: "weekly" });
    expect(mock.calls[0].body).toEqual({ cutoff_at: "2026-02-01T00:00:00.000Z", description: "weekly" });
    await c.datasets.createSnapshot();
    expect(mock.calls[1].body).toEqual({ cutoff_at: null, description: null });
    expect((await c.datasets.listSnapshots()).items).toHaveLength(1);
    expect((await c.datasets.getSnapshot(UUID)).checksum).toBe("abc");
  });
});

describe("model versions & training", () => {
  const version = (status: string, id = UUID) => ({ id, version_tag: "v1", model_type: "simplified_dgsr", status, metrics: {}, artifact_uri: null, qdrant_collection: null, created_at: "", activated_at: null });

  it("creates, lists, finds the active version and runs lifecycle actions as body-less POSTs", async () => {
    const mock = mockFetch((call) => ({ body: call.url.endsWith("/model-versions") && call.method === "GET" ? { items: [version("retired", "a"), version("active", "b")] } : version("active") }));
    const c = client(mock, { apiKey: "gr_live_x" });
    await c.modelVersions.create({ version_tag: " v1 ", model_type: "simplified_dgsr" });
    expect(mock.calls[0].body).toEqual({ version_tag: "v1", model_type: "simplified_dgsr" });
    expect((await c.modelVersions.getActive())?.id).toBe("b");
    await c.modelVersions.activate(UUID);
    expect(last(mock.calls).url).toBe(`http://api.test/v1/model-versions/${UUID}:activate`);
    await c.modelVersions.archive(UUID);
    expect(last(mock.calls).url).toBe(`http://api.test/v1/model-versions/${UUID}:archive`);
    await c.modelVersions.rollback(UUID);
    expect(last(mock.calls).url).toBe(`http://api.test/v1/models/${UUID}:rollback`);
    expect(last(mock.calls).rawBody).toBeUndefined();
    await expect(c.modelVersions.create({ version_tag: "", model_type: "x" })).rejects.toBeInstanceOf(InputValidationError);
  });

  it("maps a state conflict when archiving the active version", async () => {
    const mock = mockFetch({ status: 409, body: apiError("state_conflict", "Active version cannot be archived") });
    await expect(client(mock, { apiKey: "gr_live_x" }).modelVersions.archive(UUID)).rejects.toBeInstanceOf(StateConflictError);
  });

  it("creates a training job with defaults and polls until it finishes", async () => {
    const job = (status: string) => ({ id: "job-1", model_type: "simplified_dgsr", status, configuration: {}, dataset_snapshot_id: null, model_version_id: status === "succeeded" ? UUID : null, qdrant_collection: null, failure_reason: null, created_at: "", completed_at: null });
    let polls = 0;
    const mock = mockFetch((call) => {
      if (call.method === "POST") return { body: job("queued") };
      polls += 1;
      return { body: { items: [job(polls < 3 ? "training" : "succeeded")] } };
    });
    const c = client(mock, { apiKey: "gr_live_x" });
    const created = await c.trainingJobs.create();
    expect(mock.calls[0].body).toEqual({ model_type: "simplified_dgsr", dataset_snapshot_id: null });
    const done = await c.trainingJobs.wait(created.id, { pollIntervalMs: 1, timeoutMs: 5_000 });
    expect(done.status).toBe("succeeded");
    expect(done.model_version_id).toBe(UUID);
    expect(polls).toBe(3);
  });

  it("wait() gives up on timeout or when the job is invisible", async () => {
    const mock = mockFetch((call) => ({ body: call.url.includes("other") ? { items: [] } : { items: [{ id: "job-1", status: "training" }] } }));
    const c = client(mock, { apiKey: "gr_live_x" });
    await expect(c.trainingJobs.wait("job-1", { pollIntervalMs: 5, timeoutMs: 12 })).rejects.toBeInstanceOf(WaitTimeoutError);
    expect(await c.trainingJobs.find("nope")).toBeNull();
  });
});

describe("serving", () => {
  it("reads deployment, replicas, autoscaling and metrics", async () => {
    const mock = mockFetch({ body: { status: "ready", desired_replicas: 1, p95_latency_ms: 12 } });
    const c = client(mock, { apiKey: "gr_live_x" });
    await c.deployment.get();
    await c.deployment.replicas();
    await c.deployment.autoscaling();
    expect((await c.metrics.summary()).p95_latency_ms).toBe(12);
    expect(mock.calls.map((call) => call.url.replace("http://api.test", ""))).toEqual(["/v1/deployment", "/v1/deployment/replicas", "/v1/deployment/autoscaling", "/v1/metrics/summary"]);
  });
});

describe("recommendations & feedback", () => {
  const recs: Recommendations = {
    request_id: "rec-1",
    items: [
      { external_product_id: "sku-1", position: 1 },
      { external_product_id: "sku-2", position: 2 },
    ],
    model_version_id: UUID,
    strategy: "personalized",
    fallback_used: false,
    fallback_tier: "none",
  };
  const receipt = { event_id: "fbk_1", feedback_type: "click", accepted: true, duplicate: false, received_at: "" };

  it("requests recommendations with defaults, exclusions de-duplicated", async () => {
    const mock = mockFetch({ body: recs });
    const c = client(mock, { apiKey: "gr_live_x" });
    await c.recommendations.get();
    expect(mock.calls[0].body).toEqual({ top_n: 10, context: {} });
    await c.recommendations.get({ userId: "u1", topN: 5, context: { page: "home" }, excludeProductIds: ["a", "a", "b"] });
    expect(mock.calls[1].body).toEqual({ user_id: "u1", top_n: 5, context: { page: "home" }, exclude_product_ids: ["a", "b"] });
  });

  it("session recommendations carry the session in context", async () => {
    const mock = mockFetch({ body: recs });
    await client(mock, { apiKey: "gr_live_x" }).recommendations.forSession({ sessionId: "s1", recentProductIds: ["sku-9"], topN: 3 });
    expect(mock.calls[0].url).toBe("http://api.test/v1/recommendations/session");
    expect(mock.calls[0].body).toEqual({ top_n: 3, context: { session_id: "s1", recent_product_ids: ["sku-9"] } });
  });

  it("validates top_n, exclusions and session ids", async () => {
    const mock = mockFetch({ body: recs });
    const c = client(mock, { apiKey: "gr_live_x" });
    await expect(c.recommendations.get({ topN: 0 })).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.recommendations.get({ topN: 101 })).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.recommendations.get({ excludeProductIds: Array.from({ length: 201 }, (_, i) => `p${i}`) })).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.recommendations.forSession({ sessionId: "" })).rejects.toBeInstanceOf(InputValidationError);
    expect(mock.calls).toHaveLength(0);
  });

  it("impression feedback takes the items from the Recommendations object or an explicit list", async () => {
    const mock = mockFetch({ body: receipt });
    const c = client(mock, { apiKey: "gr_live_x" });
    await c.feedback.impression(recs);
    expect(mock.calls[0].body).toMatchObject({ request_id: "rec-1", items: recs.items, context: {} });
    expect((mock.calls[0].body as { event_id: string }).event_id).toMatch(/^fbk_/);
    expect((mock.calls[0].body as { occurred_at: string }).occurred_at).toMatch(/^\d{4}-/);
    await c.feedback.impression("rec-1", { items: ["a", "b"], eventId: "imp-1" });
    expect(mock.calls[1].body).toMatchObject({ event_id: "imp-1", items: [{ external_product_id: "a", position: 1 }, { external_product_id: "b", position: 2 }] });
    await expect(c.feedback.impression("rec-1")).rejects.toBeInstanceOf(InputValidationError);
  });

  it("click feedback derives the position and links the impression", async () => {
    const mock = mockFetch({ body: receipt });
    const c = client(mock, { apiKey: "gr_live_x" });
    await c.feedback.click(recs, "sku-2", { impressionEventId: "imp-1" });
    expect(mock.calls[0].body).toMatchObject({ request_id: "rec-1", external_product_id: "sku-2", position: 2, impression_event_id: "imp-1" });
    await c.feedback.click("rec-1", "sku-9", { position: 4 });
    expect(mock.calls[1].body).toMatchObject({ external_product_id: "sku-9", position: 4 });
    expect(mock.calls[1].body).not.toHaveProperty("impression_event_id");
    await expect(c.feedback.click("rec-1", "sku-9")).rejects.toThrow(/position is required/);
    await expect(c.feedback.click(recs, "sku-9")).rejects.toThrow(/not part of recommendation/);
    await expect(c.feedback.click(recs, "sku-1", { position: 0 })).rejects.toBeInstanceOf(InputValidationError);
    expect(positionOf(recs, "sku-2")).toBe(2);
    expect(positionOf(recs, "nope")).toBeUndefined();
  });

  it("conversion feedback sends the value as a string and tolerates a missing position", async () => {
    const mock = mockFetch({ body: receipt });
    const c = client(mock, { apiKey: "gr_live_x" });
    await c.feedback.conversion(recs, "sku-1", { value: 59 });
    expect(mock.calls[0].body).toMatchObject({ external_product_id: "sku-1", position: 1, value: "59" });
    await c.feedback.conversion("rec-1", "sku-1", { value: "12.50" });
    expect(mock.calls[1].body).toMatchObject({ value: "12.50" });
    expect(mock.calls[1].body).not.toHaveProperty("position");
    await expect(c.feedback.conversion(recs, "sku-1", { value: -1 })).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.feedback.conversion("", "sku-1")).rejects.toBeInstanceOf(InputValidationError);
  });
});

describe("platform", () => {
  const tenant = { id: UUID, slug: "acme", name: "Acme", status: "active", created_at: "" };
  const opts = { platformToken: "platform-secret" };

  it("reads status, tenants, plans, failures and audit logs", async () => {
    const mock = mockFetch((call) => ({ body: call.url.includes("/tenants/") ? tenant : call.url.endsWith("/plans") ? [{ code: "starter" }] : { items: [tenant], status: "ok" } }));
    const c = client(mock, opts);
    await c.platform.status();
    expect((await c.platform.listTenants()).items).toHaveLength(1);
    expect((await c.platform.getTenant(UUID)).slug).toBe("acme");
    expect((await c.platform.listPlans())[0].code).toBe("starter");
    await c.platform.listFailures();
    await c.platform.listAuditLogs();
    expect(mock.calls.map((call) => call.url.replace("http://api.test/v1/platform", ""))).toEqual(["/status", "/tenants", `/tenants/${UUID}`, "/plans", "/failures", "/audit"]);
    for (const call of mock.calls) expect(call.headers.authorization).toBe("Bearer platform-secret");
  });

  it("changes tenant status and quota overrides with validated bodies", async () => {
    const mock = mockFetch({ body: { ...tenant, status: "suspended", limits: {}, overrides: {} } });
    const c = client(mock, opts);
    await c.platform.setTenantStatus(UUID, "suspended");
    expect(mock.calls[0].body).toEqual({ status: "suspended" });
    await c.platform.setQuotaOverride(UUID, { accepted_events: 50_000 });
    expect(mock.calls[1].body).toEqual({ overrides: { accepted_events: 50_000 } });
    await expect(c.platform.setTenantStatus(UUID, "frozen" as never)).rejects.toBeInstanceOf(InputValidationError);
    await expect(c.platform.setQuotaOverride(UUID, { accepted_events: -1 })).rejects.toBeInstanceOf(InputValidationError);
  });
});

describe("client helpers", () => {
  it("health() needs no credentials and withCredentials() keeps the server", async () => {
    const mock = mockFetch({ body: { status: "ok" } });
    const c = client(mock);
    expect((await c.health()).status).toBe("ok");
    expect(mock.calls[0].url).toBe("http://api.test/healthz");
    const store = c.withCredentials({ apiKey: "gr_live_y" });
    await store.products.list();
    expect(mock.calls[1].url).toBe("http://api.test/v1/products");
    expect(mock.calls[1].headers.authorization).toBe("ApiKey gr_live_y");
    expect(store.baseUrl).toBe(c.baseUrl);
  });

  it("sends default and per-request headers and the SDK user agent", async () => {
    const mock = mockFetch({ body: {} });
    const c = client(mock, { apiKey: "gr_live_x", defaultHeaders: { "X-Shop-Region": "eu" } });
    await c.request("products.list", { headers: { "X-Trace": "1" }, correlationId: "corr-1" });
    expect(mock.calls[0].headers["x-shop-region"]).toBe("eu");
    expect(mock.calls[0].headers["x-trace"]).toBe("1");
    expect(mock.calls[0].headers["x-correlation-id"]).toBe("corr-1");
    expect(mock.calls[0].headers["user-agent"]).toMatch(/^graphrec-sdk-ts\/\d+\.\d+\.\d+/);
  });
});
