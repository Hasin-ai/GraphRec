import { GraphRec, type GraphRecOptions } from "../src/index.js";

export interface Call {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
  rawBody: BodyInit | null | undefined;
}

export interface Reply {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
  /** Throw instead of answering (transport failure). */
  throws?: unknown;
  /** Never resolve within this many ms (to trigger the client timeout). */
  hangMs?: number;
}

export type Handler = (call: Call, index: number) => Reply | Promise<Reply>;

export interface Mock {
  calls: Call[];
  fetch: typeof fetch;
}

function headerRecord(init: HeadersInit | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!init) return out;
  if (init instanceof Headers) init.forEach((v, k) => (out[k.toLowerCase()] = v));
  else if (Array.isArray(init)) for (const [k, v] of init) out[k.toLowerCase()] = v;
  else for (const [k, v] of Object.entries(init)) out[k.toLowerCase()] = v;
  return out;
}

/** A fetch that answers from `handler` and records every call. */
export function mockFetch(handler: Handler | Reply | Reply[]): Mock {
  const calls: Call[] = [];
  const resolve: Handler = typeof handler === "function" ? handler : Array.isArray(handler) ? (_c, i) => handler[Math.min(i, handler.length - 1)] : () => handler;
  const fetchImpl = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const rawBody = init.body;
    let body: unknown = null;
    if (typeof rawBody === "string") {
      try {
        body = JSON.parse(rawBody);
      } catch {
        body = rawBody;
      }
    } else if (rawBody instanceof FormData) body = rawBody;
    const call: Call = { method: init.method ?? "GET", url, headers: headerRecord(init.headers), body, rawBody };
    calls.push(call);
    const reply = await resolve(call, calls.length - 1);
    if (reply.throws !== undefined) throw reply.throws;
    if (reply.hangMs !== undefined) {
      await new Promise<void>((_res, rej) => {
        const t = setTimeout(() => rej(Object.assign(new Error("aborted"), { name: "AbortError" })), reply.hangMs);
        init.signal?.addEventListener("abort", () => {
          clearTimeout(t);
          rej(Object.assign(new Error("aborted"), { name: "AbortError" }));
        });
      });
    }
    const status = reply.status ?? 200;
    const text = reply.body === undefined ? "" : typeof reply.body === "string" ? reply.body : JSON.stringify(reply.body);
    return new Response(text, { status, headers: { "Content-Type": "application/json", "X-Correlation-ID": "cid-1", ...(reply.headers ?? {}) } });
  }) as typeof fetch;
  return { calls, fetch: fetchImpl };
}

export function client(mock: Mock, options: GraphRecOptions = {}): GraphRec {
  return new GraphRec({ baseUrl: "http://api.test", useEnv: false, fetch: mock.fetch, retry: { initialDelayMs: 1, maxDelayMs: 2, ...(options.retry ?? {}) }, ...options });
}

export function apiError(code: string, message = code, extra: Record<string, unknown> = {}): unknown {
  return { error: { code, message, correlation_id: "cid-err", retryable: false, ...extra } };
}

export const TOKEN = {
  access_token: "h.p.s",
  token_type: "Bearer" as const,
  expires_in: 900,
  refresh_token: "r",
  user_role: "tenant_administrator" as const,
  scopes: ["keys:write", "catalog:read", "catalog:write", "events:read", "events:write"],
};
