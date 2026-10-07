import { afterEach, describe, expect, it, vi } from "vitest";
import { getTenantSession, setTenantSession } from "../auth/session";
import { mockFetch, signInAsAdmin, tokenPair } from "../test/helpers";
import { describeError, request } from "./client";
import { GraphRecApiError } from "./types";

afterEach(() => vi.unstubAllGlobals());

describe("session refresh (A-05)", () => {
  it("refreshes an expired access token once and retries the request with the new one", async () => {
    setTenantSession("a@example.org", tokenPair({ access_token: "old", refresh_token: "r1" }));
    const calls: { url: string; auth?: string; body?: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      const headers = init.headers as Record<string, string>;
      calls.push({ url, auth: headers.Authorization, body: init.body as string | undefined });
      if (url.endsWith("/v1/auth/refresh")) return new Response(JSON.stringify(tokenPair({ access_token: "new", refresh_token: "r2" })));
      if (headers.Authorization === "Bearer old") return new Response(JSON.stringify({ error: { code: "token_expired", message: "expired" } }), { status: 401 });
      return new Response(JSON.stringify({ items: [] }));
    }));
    await expect(request("/v1/products")).resolves.toEqual({ items: [] });
    expect(calls.map(c => c.url.replace(/^.*\/v1/, "/v1"))).toEqual(["/v1/products", "/v1/auth/refresh", "/v1/products"]);
    expect(JSON.parse(calls[1].body!)).toEqual({ refresh_token: "r1" });
    expect(calls[2].auth).toBe("Bearer new");
    expect(getTenantSession()?.refreshToken).toBe("r2");
  });
  it("shares one refresh between concurrent requests (refresh tokens are single-use)", async () => {
    setTenantSession("a@example.org", { ...tokenPair({ access_token: "old", refresh_token: "r1" }), expires_in: 0 });
    let refreshes = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/v1/auth/refresh")) { refreshes++; return new Response(JSON.stringify(tokenPair({ access_token: "new", refresh_token: "r2" }))); }
      return new Response(JSON.stringify({ ok: true }));
    }));
    await Promise.all([request("/v1/products"), request("/v1/usage"), request("/v1/deployment")]);
    expect(refreshes).toBe(1);
  });
  it("signs out when the refresh token is rejected", async () => {
    setTenantSession("a@example.org", { ...tokenPair({ access_token: "old", refresh_token: "stolen" }), expires_in: 0 });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "invalid_refresh_token", message: "x" } }), { status: 401 })));
    await expect(request("/v1/products")).rejects.toMatchObject({ code: "invalid_refresh_token" });
    expect(getTenantSession()).toBeNull();
  });
});

describe("request", () => {
  it("does not deliver an old account's mutation result into a new session", async () => {
    setTenantSession('a@example.org', tokenPair({ access_token: 'a' }));
    let finish!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
    const pending = request('/v1/api-keys', { method: 'POST', json: { name: 'old account key' } });
    setTenantSession('b@example.org', tokenPair({ access_token: 'b' }));
    finish(new Response(JSON.stringify({ secret: 'old-secret' })));
    await expect(pending).rejects.toMatchObject({ code: 'session_changed' });
    expect(getTenantSession()?.accessToken).toBe('b');
  });
  it("does not expire a newer session when an obsolete request returns 401", async () => {
    setTenantSession('a@example.org', tokenPair({ access_token: 'old' }));
    let finish!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
    const old = request('/v1/products').catch(error => error);
    setTenantSession('b@example.org', tokenPair({ access_token: 'new' }));
    finish(new Response(JSON.stringify({ error: { code: 'token_expired' } }), { status: 401 }));
    await old;
    expect(getTenantSession()?.accessToken).toBe('new');
  });
  it("deduplicates simultaneous reads but never shares them across sessions", async () => {
    setTenantSession('a@example.org', tokenPair({ access_token: 'a' }));
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ items: [] })));
    vi.stubGlobal('fetch', fetcher);
    const a = request('/v1/products'); const duplicate = request('/v1/products');
    setTenantSession('b@example.org', tokenPair({ access_token: 'b' }));
    const results = await Promise.allSettled([a, duplicate, request('/v1/products')]);
    expect(results.map(result => result.status)).toEqual(['rejected', 'rejected', 'fulfilled']);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("rejects a successful HTTP response containing HTML instead of JSON", async () => {
    signInAsAdmin();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>Proxy failure</html>')));
    await expect(request('/v1/usage')).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it("sends JSON headers only when there is a body, and the bearer token for the tenant realm", async () => {
    signInAsAdmin();
    const { calls } = mockFetch([
      { path: "/v1/products", body: { items: [], total: 0 } },
      { method: "POST", path: "/v1/products/SKU-1:disable", body: { external_id: "SKU-1" } },
      { method: "PUT", path: "/v1/products/SKU-1", body: { external_id: "SKU-1" } },
    ]);
    await request("/v1/products");
    await request("/v1/products/SKU-1:disable", { method: "POST" });
    await request("/v1/products/SKU-1", { method: "PUT", json: { title: "x" } });

    const headers = (i: number) => calls[i].init.headers as Record<string, string>;
    expect(headers(0).Authorization).toBe("Bearer header.payload.signature");
    expect(headers(0).Accept).toBe("application/json");
    expect(headers(1)["Content-Type"]).toBeUndefined();
    expect(calls[1].init.body).toBeUndefined();
    expect(headers(2)["Content-Type"]).toBe("application/json");
    expect(calls[2].init.body).toBe(JSON.stringify({ title: "x" }));
  });

  it("unwraps the error envelope into GraphRecApiError with the correlation id", async () => {
    signInAsAdmin();
    mockFetch([{ path: "/v1/usage", status: 429, body: { error: { code: "rate_limit_exceeded", message: "Usage read limit exceeded", correlation_id: "abc", retryable: true, retry_after_seconds: 7 } } }]);
    const error = await request("/v1/usage").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(GraphRecApiError);
    const apiError = error as GraphRecApiError;
    expect(apiError.status).toBe(429);
    expect(apiError.code).toBe("rate_limit_exceeded");
    expect(apiError.correlationId).toBe("abc");
    expect(apiError.retryAfterSeconds).toBe(7);
    expect(describeError(apiError)).toContain("7 seconds");
  });

  it("shows the server's training cooldown retry time", () => {
    const error = new GraphRecApiError(409, { error: { code: "training_cooldown", retry_after_seconds: 42 } });
    expect(describeError(error)).toBe("Training is cooling down. Try again in 42 seconds.");
  });

  it("ends the tenant session on 401 so the guards route to sign-in", async () => {
    // A-05: an expired token is refreshed first; the session ends only when that fails.
    signInAsAdmin();
    mockFetch([
      { path: "/v1/api-keys", status: 401, body: { error: { code: "token_expired", message: "Access token expired" } } },
      { method: "POST", path: "/v1/auth/refresh", status: 401, body: { error: { code: "invalid_refresh_token", message: "Sign in again" } } },
    ]);
    await expect(request("/v1/api-keys")).rejects.toMatchObject({ code: "invalid_refresh_token" });
    expect(getTenantSession()).toBeNull();
  });

  it("ends a session without a refresh token on token_expired", async () => {
    setTenantSession("a@example.org", tokenPair({ refresh_token: "" }));
    mockFetch([{ path: "/v1/api-keys", status: 401, body: { error: { code: "token_expired", message: "Access token expired" } } }]);
    await expect(request("/v1/api-keys")).rejects.toMatchObject({ code: "token_expired" });
    expect(getTenantSession()).toBeNull();
  });

  it("refuses a tenant call without a session before touching the network", async () => {
    const { calls } = mockFetch([]);
    await expect(request("/v1/api-keys")).rejects.toMatchObject({ code: "no_session" });
    expect(calls).toHaveLength(0);
  });

  it("maps a network failure to a retryable-looking client error", async () => {
    signInAsAdmin();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const error = (await request("/v1/api-keys").catch((e: unknown) => e)) as GraphRecApiError;
    expect(error.code).toBe("network_error");
    expect(describeError(error)).toMatch(/could not be reached/);
  });
});
