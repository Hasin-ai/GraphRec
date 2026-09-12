import { describe, expect, it } from "vitest";
import {
  APIConnectionError,
  APITimeoutError,
  AuthenticationError,
  ConfigurationError,
  DuplicateResourceError,
  GraphRec,
  NotFoundError,
  PermissionDeniedError,
  QuotaExceededError,
  RateLimitError,
  RequestValidationError,
  ServiceUnavailableError,
  TokenExpiredError,
} from "../src/index.js";
import { TOKEN, apiError, client, mockFetch } from "./helpers.js";

describe("credentials", () => {
  it("sends an API key as ApiKey and a token as Bearer", async () => {
    const mock = mockFetch({ body: { items: [], total: 0 } });
    await client(mock, { apiKey: "gr_live_abc" }).products.list();
    await client(mock, { accessToken: "tok" }).products.list();
    expect(mock.calls[0].headers.authorization).toBe("ApiKey gr_live_abc");
    expect(mock.calls[1].headers.authorization).toBe("Bearer tok");
    expect(mock.calls[0].headers.accept).toBe("application/json");
    expect(mock.calls[0].headers["content-type"]).toBeUndefined();
  });

  it("never sends credentials to public routes", async () => {
    const mock = mockFetch({ body: TOKEN });
    await client(mock, { apiKey: "gr_live_abc" }).auth.login({ email: "A@B.C", password: "x" });
    expect(mock.calls[0].headers.authorization).toBeUndefined();
    expect(mock.calls[0].body).toEqual({ email: "a@b.c", password: "x" });
  });

  it("refuses API-key management with an API key and tenant routes with the platform token, before sending", async () => {
    const mock = mockFetch({ body: {} });
    await expect(client(mock, { apiKey: "gr_live_abc" }).apiKeys.list()).rejects.toBeInstanceOf(ConfigurationError);
    await expect(client(mock, { platformToken: "secret" }).products.list()).rejects.toBeInstanceOf(ConfigurationError);
    await expect(client(mock, { apiKey: "gr_live_abc" }).platform.status()).rejects.toBeInstanceOf(ConfigurationError);
    await expect(client(mock).products.list()).rejects.toBeInstanceOf(ConfigurationError);
    expect(mock.calls).toHaveLength(0);
  });

  it("rejects contradictory or malformed credentials", () => {
    expect(() => new GraphRec({ useEnv: false, apiKey: "nope" })).toThrow(ConfigurationError);
    expect(() => new GraphRec({ useEnv: false, apiKey: "gr_live_a", accessToken: "t" })).toThrow(ConfigurationError);
    expect(() => new GraphRec({ useEnv: false, email: "a@b.c" })).toThrow(ConfigurationError);
  });

  it("platform token is a bearer on platform routes only", async () => {
    const mock = mockFetch({ body: { items: [] } });
    await client(mock, { platformToken: "secret" }).platform.listTenants();
    expect(mock.calls[0].headers.authorization).toBe("Bearer secret");
    expect(mock.calls[0].url).toBe("http://api.test/v1/platform/tenants");
  });

  it("password credentials log in once, reuse the token, and log in again on token_expired", async () => {
    const mock = mockFetch((call, i) => {
      if (call.url.endsWith("/v1/auth/login")) return { body: TOKEN };
      if (i === 2) return { status: 401, body: apiError("token_expired", "Access token expired") };
      return { body: { items: [], total: 0 } };
    });
    const c = client(mock, { email: "owner@shop.example", password: "pw" });
    await c.products.list();
    await c.products.list();
    expect(mock.calls.map((x) => x.url.split("/v1/")[1])).toEqual(["auth/login", "products", "products", "auth/login", "products"]);
    expect(mock.calls[1].headers.authorization).toBe("Bearer h.p.s");
    expect(c.sessionScopes).toContain("catalog:write");
  });

  it("marks a replayed registration", async () => {
    const mock = mockFetch([
      { status: 201, body: { id: "t", name: "Acme", status: "active", created_at: "x", administrator_email: "o@a.c", next_step: "…", setup_token: "tok_1234567890abcdef", setup_token_expires_at: "y" } },
      { status: 200, body: { id: "t", name: "Acme", status: "active", created_at: "x", administrator_email: "o@a.c", next_step: "…", setup_token: null, setup_token_expires_at: null } },
    ]);
    const c = client(mock);
    const first = await c.tenants.register({ name: " Acme ", admin_email: "O@a.c" }, { idempotencyKey: "k1" });
    const second = await c.tenants.register({ name: "Acme", admin_email: "o@a.c" }, { idempotencyKey: "k1" });
    expect(first.replayed).toBe(false);
    expect(second.replayed).toBe(true);
    expect(mock.calls[0].headers["idempotency-key"]).toBe("k1");
    expect(mock.calls[0].body).toEqual({ name: "Acme", admin_email: "o@a.c" });
  });
});

describe("errors", () => {
  const cases: [string, number, unknown][] = [
    ["resource_not_found", 404, NotFoundError],
    ["insufficient_scope", 403, PermissionDeniedError],
    ["authentication_failed", 401, AuthenticationError],
    ["invalid_setup_token", 401, AuthenticationError],
    ["token_expired", 401, TokenExpiredError],
    ["duplicate_resource", 409, DuplicateResourceError],
    ["validation_failed", 422, RequestValidationError],
    ["quota_exceeded", 429, QuotaExceededError],
  ];
  for (const [code, status, cls] of cases) {
    it(`maps ${code} to ${(cls as { name: string }).name}`, async () => {
      const mock = mockFetch({ status, body: apiError(code) });
      const error = await client(mock, { apiKey: "gr_live_a" }).products.get("x").catch((e: unknown) => e);
      expect(error).toBeInstanceOf(cls as never);
      expect((error as { correlationId: string }).correlationId).toBe("cid-err");
      expect((error as { code: string }).code).toBe(code);
    });
  }

  it("exposes field errors and falls back to the status when the envelope is missing", async () => {
    const mock = mockFetch([
      { status: 422, body: apiError("validation_failed", "bad", { details: { fields: [{ field: "price", message: "must be >= 0" }] } }) },
      { status: 503, body: "<html>bad gateway</html>", headers: { "Retry-After": "7" } },
    ]);
    const c = client(mock, { apiKey: "gr_live_a", retry: { maxRetries: 0 } });
    const v = (await c.products.get("x").catch((e: unknown) => e)) as RequestValidationError;
    expect(v.fieldErrors).toEqual([{ field: "price", message: "must be >= 0" }]);
    const s = (await c.products.get("x").catch((e: unknown) => e)) as ServiceUnavailableError;
    expect(s).toBeInstanceOf(ServiceUnavailableError);
    expect(s.retryAfterSeconds).toBe(7);
    expect(s.code).toBe("http_503");
  });

  it("wraps transport failures and timeouts", async () => {
    const refused = mockFetch({ throws: Object.assign(new TypeError("fetch failed"), { cause: { code: "ECONNREFUSED" } }) });
    await expect(client(refused, { apiKey: "gr_live_a", retry: { maxRetries: 0 } }).products.list()).rejects.toBeInstanceOf(APIConnectionError);
    const slow = mockFetch({ hangMs: 5_000 });
    await expect(client(slow, { apiKey: "gr_live_a", timeoutMs: 20, retry: { maxRetries: 0 } }).products.list()).rejects.toBeInstanceOf(APITimeoutError);
  });
});

describe("retries", () => {
  it("retries 429 honouring retry_after_seconds, then succeeds", async () => {
    const mock = mockFetch([{ status: 429, body: apiError("rate_limit_exceeded", "slow down", { retryable: true, retry_after_seconds: 0.01 }) }, { body: { items: [], total: 0 } }]);
    const started = Date.now();
    await client(mock, { apiKey: "gr_live_a" }).products.list();
    expect(mock.calls).toHaveLength(2);
    expect(Date.now() - started).toBeGreaterThanOrEqual(5);
  });

  it("gives up after maxRetries and surfaces the RateLimitError", async () => {
    const mock = mockFetch({ status: 429, body: apiError("rate_limit_exceeded", "slow", { retry_after_seconds: 0 }) });
    await expect(client(mock, { apiKey: "gr_live_a", retry: { maxRetries: 2 } }).products.list()).rejects.toBeInstanceOf(RateLimitError);
    expect(mock.calls).toHaveLength(3);
  });

  it("never retries quota_exceeded or plain 4xx", async () => {
    const quota = mockFetch({ status: 429, body: apiError("quota_exceeded", "over", { retryable: true, retry_after_seconds: 0 }) });
    await expect(client(quota, { apiKey: "gr_live_a" }).events.create({ event_type: "view" })).rejects.toBeInstanceOf(QuotaExceededError);
    expect(quota.calls).toHaveLength(1);
    const notFound = mockFetch({ status: 404, body: apiError("resource_not_found") });
    await expect(client(notFound, { apiKey: "gr_live_a" }).products.get("x")).rejects.toBeInstanceOf(NotFoundError);
    expect(notFound.calls).toHaveLength(1);
  });

  it("retries a 502 only on idempotent routes", async () => {
    const idem = mockFetch([{ status: 502, body: "" }, { body: { items: [] } }]);
    await client(idem, { accessToken: "t" }).modelVersions.list();
    expect(idem.calls).toHaveLength(2);
    const nonIdem = mockFetch([{ status: 502, body: "" }, { body: {} }]);
    await expect(client(nonIdem, { accessToken: "t" }).trainingJobs.create()).rejects.toMatchObject({ status: 502 });
    expect(nonIdem.calls).toHaveLength(1);
  });

  it("retries an ambiguous transport failure only on idempotent routes", async () => {
    const idem = mockFetch([{ throws: new TypeError("socket hang up") }, { body: { items: [], total: 0 } }]);
    await client(idem, { apiKey: "gr_live_a" }).products.list();
    expect(idem.calls).toHaveLength(2);
    const nonIdem = mockFetch([{ throws: new TypeError("socket hang up") }, { body: {} }]);
    await expect(client(nonIdem, { accessToken: "t" }).apiKeys.create({ name: "k", scopes: ["catalog:read"] })).rejects.toBeInstanceOf(APIConnectionError);
    expect(nonIdem.calls).toHaveLength(1);
  });
});
