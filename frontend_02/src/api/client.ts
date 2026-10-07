import {
  clearPlatformSession,
  clearTenantSession,
  getPlatformSession,
  getTenantSession,
  setTenantSession,
} from "../auth/session";
import { GraphRecApiError, type AuthTokenPair, type ErrorBody } from "./types";

export type Realm = "public" | "tenant" | "platform";
export const RESOURCE_CHANGED = "graphrec:resource-changed";
const pendingReads = new Map<string, Promise<unknown>>();

/**
 * Where the API lives. Empty by default: the console is served by nginx, which
 * proxies /v1 to the API, so relative paths keep the browser on one origin.
 * Set VITE_API_BASE_URL at build time to point a dev server at another host.
 */
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

/** Absolute URL for an API path ("/v1/products" -> base + path). */
export function apiUrl(path: string): string {
  return path.startsWith("/") ? BASE_URL + path : path;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** JSON body; serialised and sent with Content-Type: application/json. */
  json?: unknown;
  /** Multipart body (dataset upload); sent as-is with no Content-Type so the browser sets the boundary. */
  form?: FormData;
  headers?: Record<string, string>;
  realm?: Realm;
}

function authorization(realm: Realm): string | null {
  if (realm === "tenant") {
    const session = getTenantSession();
    if (!session) throw new GraphRecApiError(401, { error: { code: "no_session", message: "Sign in to continue" } });
    return `Bearer ${session.accessToken}`;
  }
  if (realm === "platform") {
    const session = getPlatformSession();
    if (!session) throw new GraphRecApiError(401, { error: { code: "no_session", message: "Sign in to continue" } });
    return `Bearer ${session.token}`;
  }
  return null;
}

/**
 * One fetch wrapper for every endpoint. It applies the contract the API's
 * ContractMiddleware enforces (JSON Accept, JSON Content-Type only when there
 * is a body), unwraps the error envelope into GraphRecApiError, and ends the
 * realm's session on an authentication failure so the guards route to sign-in.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const realm = options.realm ?? "tenant";
  if (realm === "tenant" && needsRefresh()) await refreshTenantSession();
  const sentWith = realm === "tenant" ? getTenantSession()?.accessToken : undefined;
  try {
    return await dispatch<T>(path, options, realm);
  } catch (error) {
    // The token expired between the check and the call: refresh once and retry,
    // but only for the session that sent it (a newer sign-in is left alone).
    const current = getTenantSession();
    if (realm === "tenant" && error instanceof GraphRecApiError && error.code === "token_expired"
        && current?.refreshToken && current.accessToken === sentWith) {
      await refreshTenantSession();
      return dispatch<T>(path, options, realm);
    }
    throw error;
  }
}

/** Renew a little before expiry so a request never leaves with a dead token. */
const REFRESH_MARGIN_MS = 30_000;
let refreshing: Promise<void> | null = null;

function needsRefresh(): boolean {
  const session = getTenantSession();
  return !!session?.refreshToken && session.expiresAt - REFRESH_MARGIN_MS <= Date.now();
}

/**
 * Rotate the refresh token (single flight: concurrent requests share one call,
 * because a refresh token works exactly once and a second use signs the user out).
 */
export function refreshTenantSession(): Promise<void> {
  refreshing ??= (async () => {
    const session = getTenantSession();
    try {
      if (!session?.refreshToken) throw new GraphRecApiError(401, { error: { code: "no_session", message: "Sign in to continue" } });
      const pair = await performRequest<AuthTokenPair>("/v1/auth/refresh", { method: "POST", json: { refresh_token: session.refreshToken }, realm: "public" }, null);
      setTenantSession(pair.email ?? session.email, pair, session.signedInAt);
    } catch (error) {
      if (!(error instanceof GraphRecApiError) || error.status === 401) clearTenantSession();
      throw error;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function dispatch<T>(path: string, options: RequestOptions, realm: Realm): Promise<T> {
  const identity = authorization(realm);
  const key = JSON.stringify([realm, identity, path, options.headers]);
  if ((options.method ?? "GET") === "GET") {
    const pending = pendingReads.get(key);
    if (pending) return pending as Promise<T>;
    const promise = performRequest<T>(path, options, identity);
    pendingReads.set(key, promise);
    try { return await promise; }
    finally { if (pendingReads.get(key) === promise) pendingReads.delete(key); }
  }
  const result = await performRequest<T>(path, options, identity);
  pendingReads.clear();
  window.dispatchEvent(new CustomEvent(RESOURCE_CHANGED, { detail: path }));
  return result;
}

async function performRequest<T>(path: string, options: RequestOptions, auth: string | null): Promise<T> {
  const realm = options.realm ?? "tenant";
  const headers: Record<string, string> = { Accept: "application/json", ...(options.headers ?? {}) };
  if (auth) headers.Authorization = auth;

  let body: BodyInit | undefined;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  } else if (options.form) {
    body = options.form;
  }

  let response: Response;
  try {
    response = await fetch(apiUrl(path), { method: options.method ?? "GET", headers, body });
  } catch {
    throw new GraphRecApiError(0, { error: { code: "network_error", message: "GraphRec could not be reached" } });
  }

  const correlationId = response.headers.get("X-Correlation-ID") ?? undefined;
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    const error = new GraphRecApiError(response.status, parsed as ErrorBody | null, correlationId);
    const refreshable = error.code === "token_expired" && !!getTenantSession()?.refreshToken;
    if (response.status === 401 && realm === "tenant" && !refreshable && auth === `Bearer ${getTenantSession()?.accessToken}`) clearTenantSession();
    if (response.status === 401 && realm === "platform" && auth === `Bearer ${getPlatformSession()?.token}`) clearPlatformSession();
    throw error;
  }
  const currentAuth = realm === "tenant" ? `Bearer ${getTenantSession()?.accessToken}` : realm === "platform" ? `Bearer ${getPlatformSession()?.token}` : null;
  if (auth !== currentAuth) throw new GraphRecApiError(409, { error: { code: "session_changed", message: "The signed-in account changed while this request was pending. Reload to check its outcome." } });
  if (parsed === null && response.status !== 204) throw new GraphRecApiError(response.status, { error: { code: "invalid_response", message: "The API returned an unreadable response. Try again." } }, correlationId);
  return parsed as T;
}

export function isApiError(error: unknown): error is GraphRecApiError {
  return error instanceof GraphRecApiError;
}

/** Human-readable, non-disclosing message for an unexpected failure. */
export function describeError(error: unknown): string {
  if (!isApiError(error)) return "Something went wrong. Try again shortly.";
  if (error.code === "network_error") return "GraphRec could not be reached. Check that the API is running.";
  if (error.code === "rate_limit_exceeded")
    return `Too many requests. Try again in ${error.retryAfterSeconds ?? "a few"} seconds.`;
  if (error.code === "training_cooldown")
    return `Training is cooling down. Try again in ${error.retryAfterSeconds ?? "a few"} seconds.`;
  if (error.code === "insufficient_scope") return "Your credential does not grant this operation.";
  if (error.code === "token_expired") return "Your session expired. Sign in again.";
  if (error.code === "internal_error")
    return `Something went wrong on our side${error.correlationId ? ` (reference ${error.correlationId})` : ""}. Try again shortly.`;
  if (error.code === "validation_failed" && error.fields.length) {
    return error.fields.map((f) => `${f.field}: ${f.message}`).join("; ");
  }
  return error.message;
}
