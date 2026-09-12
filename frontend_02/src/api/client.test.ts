import { afterEach, describe, expect, it, vi } from "vitest";
import { getTenantSession } from "../auth/session";
import { mockFetch, signInAsAdmin } from "../test/helpers";
import { describeError, request } from "./client";
import { GraphRecApiError } from "./types";

afterEach(() => vi.unstubAllGlobals());

describe("request", () => {
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

  it("ends the tenant session on 401 so the guards route to sign-in", async () => {
    signInAsAdmin();
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
