import { describe, expect, it } from "vitest";
import { MAX_EVENT_ID_LENGTH, ROUTES, buildPath, deterministicId, newId, newIdempotencyKey, requiredScopes, route } from "../src/index.js";

describe("identifiers", () => {
  it("newId is unique, prefixed and short enough for an event_id", () => {
    const ids = new Set(Array.from({ length: 1000 }, () => newId("evt")));
    expect(ids.size).toBe(1000);
    for (const id of ids) {
      expect(id).toMatch(/^evt_[0-9a-f]{32}$/);
      expect(id.length).toBeLessThanOrEqual(MAX_EVENT_ID_LENGTH);
    }
    expect(newId()).toMatch(/^[0-9a-f]{32}$/);
    expect(newIdempotencyKey()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("deterministicId is stable and matches the Python SDK byte for byte", () => {
    // Expected values computed with graphrec_sdk._ids.deterministic_id.
    expect(deterministicId("purchase", "ORD-1", 1, { prefix: "evt" })).toBe("evt_4dde6e62e4582a1296759910b0ea6935cbeca719");
    expect(deterministicId("order", 1042, "line", 2)).toBe("01b79b76d46f3eb0377dfe0d1a24393320ec69e5");
    expect(deterministicId("a", null, true, 1.5)).toBe("be3ae2a251de60b4258c6343bfa0494d9aa48f0b");
    expect(deterministicId("purchase", "ORD-1001", "sku-100", { prefix: "evt" })).toBe("evt_512765915d2fb2861c182d11438721fcff2858a6");
  });

  it("deterministicId separates parts so ('ab', 'c') and ('a', 'bc') differ", () => {
    expect(deterministicId("ab", "c")).not.toBe(deterministicId("a", "bc"));
    expect(deterministicId("x")).toBe(deterministicId("x"));
    expect(deterministicId("x", { prefix: "" })).toBe(deterministicId("x"));
    expect(() => deterministicId()).toThrow(RangeError);
    expect(() => deterministicId({ prefix: "evt" })).toThrow(RangeError);
  });

  it("deterministicId never exceeds the event_id limit", () => {
    expect(deterministicId("x", { prefix: "p".repeat(200) })).toHaveLength(MAX_EVENT_ID_LENGTH);
  });
});

describe("route table", () => {
  it("holds 50 routes with unique method+path pairs", () => {
    expect(ROUTES.size).toBe(50);
    const pairs = new Set([...ROUTES.values()].map((r) => `${r.method} ${r.path}`));
    expect(pairs.size).toBe(50);
  });

  it("builds and encodes paths, and reports missing or empty parameters", () => {
    expect(buildPath(route("products.get"), { external_id: "sku/1 ä" })).toBe("/v1/products/sku%2F1%20%C3%A4");
    expect(buildPath(route("products.list"))).toBe("/v1/products");
    expect(() => buildPath(route("products.get"))).toThrow(/Missing path parameter/);
    expect(() => buildPath(route("products.get"), { external_id: "" })).toThrow(/must not be empty/);
    expect(() => route("nope")).toThrow(/Unknown GraphRec route/);
  });

  it("lists every scope a route needs", () => {
    expect(requiredScopes(route("datasets.upload"))).toEqual(["catalog:write", "events:write"]);
    expect(requiredScopes(route("health.check"))).toEqual([]);
    expect(requiredScopes(route("api_keys.list"))).toEqual(["keys:write"]);
  });

  it("marks writes with server-side deduplication as idempotent and the rest as not", () => {
    for (const key of ["events.create", "events.create_batch", "products.bulk_upsert", "tenants.register", "feedback.click"]) expect(route(key).idempotent, key).toBe(true);
    for (const key of ["api_keys.create", "api_keys.rotate", "training_jobs.create", "model_versions.create", "datasets.upload", "datasets.create_snapshot"]) expect(route(key).idempotent, key).toBe(false);
    for (const r of ROUTES.values()) if (r.method === "GET") expect(r.idempotent, r.key).toBe(true);
  });
});
