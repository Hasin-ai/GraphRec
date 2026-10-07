import { vi } from "vitest";
import { setPlatformSession, setTenantSession } from "../auth/session";
import type { AuthTokenPair } from "../api/types";

export const ADMIN_SCOPES = [
  "keys:write", "billing:read", "usage:read", "catalog:read", "catalog:write", "events:read", "events:write",
  "training:read", "training:write", "models:read", "models:write", "models:deploy", "recommendations:read",
  "deployments:read", "metrics:read",
];
export const DEVELOPER_SCOPES = ["keys:write", "catalog:read", "catalog:write", "events:read", "events:write", "training:read"];

export function tokenPair(overrides: Partial<AuthTokenPair> = {}): AuthTokenPair {
  return {
    access_token: "header.payload.signature",
    token_type: "Bearer",
    expires_in: 900,
    refresh_token: "refresh",
    user_role: "tenant_administrator",
    scopes: ADMIN_SCOPES,
    ...overrides,
  };
}

export function signInAsAdmin(): void {
  setTenantSession("dana@northgate.example", tokenPair());
}

export function signInAsDeveloper(): void {
  setTenantSession("ruben@northgate.example", tokenPair({ user_role: "tenant_developer", scopes: DEVELOPER_SCOPES }));
}

export function signInAsPlatform(): void {
  setPlatformSession("platform-token");
}

export interface MockRoute {
  method?: string;
  path: string | RegExp;
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
}

/** Installs a fetch mock that answers from a route table and records every call. */
export function mockFetch(routes: MockRoute[]): { calls: { url: string; init: RequestInit }[] } {
  const calls: { url: string; init: RequestInit }[] = [];
  const impl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    calls.push({ url, init });
    const method = (init.method ?? "GET").toUpperCase();
    const route = routes.find((r) => (r.method ?? "GET").toUpperCase() === method && (typeof r.path === "string" ? r.path === url : r.path.test(url)));
    if (!route) return new Response(JSON.stringify({ error: { code: "resource_not_found", message: `no mock for ${method} ${url}` } }), { status: 404, headers: { "Content-Type": "application/json" } });
    const status = route.status ?? 200;
    const body = route.body === undefined ? "" : JSON.stringify(route.body);
    return new Response(body, { status, headers: { "Content-Type": "application/json", "X-Correlation-ID": "11111111-1111-1111-1111-111111111111", ...(route.headers ?? {}) } });
  });
  vi.stubGlobal("fetch", impl);
  return { calls };
}
