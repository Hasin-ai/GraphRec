import {
  clearPlatformSession,
  clearTenantSession,
  getPlatformSession,
  getTenantSession,
} from "../auth/session";
import { GraphRecApiError, type ErrorBody } from "./types";

export type Realm = "public" | "tenant" | "platform";

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
  const headers: Record<string, string> = { Accept: "application/json", ...(options.headers ?? {}) };
  const auth = authorization(realm);
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
    response = await fetch(path, { method: options.method ?? "GET", headers, body });
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
    if (response.status === 401 && realm === "tenant" && error.code !== "no_session") clearTenantSession();
    if (response.status === 401 && realm === "platform" && error.code !== "no_session") clearPlatformSession();
    throw error;
  }
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
  if (error.code === "insufficient_scope") return "Your credential does not grant this operation.";
  if (error.code === "token_expired") return "Your session expired. Sign in again.";
  if (error.code === "validation_failed" && error.fields.length) {
    return error.fields.map((f) => `${f.field}: ${f.message}`).join("; ");
  }
  return error.message;
}
