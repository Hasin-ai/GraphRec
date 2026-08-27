import { GraphRec } from '../src/index.js';
import type { GraphRecOptions } from '../src/index.js';

export const TENANT = '3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d';
export const TENANT_HEX = '3f2b1c4d5e6f4a7b8c9d0e1f2a3b4c5d';
export const KEY = 'gr_live_7Kq4.Zm9vYmFyYmF6cXV1eGNvcmdlZ3JhdWx0Z2FycGx5';

export interface Call {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
}

export interface Reply {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
  /** Thrown instead of answering — a connect or TLS failure. */
  throws?: Error;
}

/**
 * A recording fetch that answers from a script.
 *
 * Not a mock of `fetch` so much as a tiny server: the tests below assert on what
 * was *sent*, which a stub that only returns values cannot support. A reply
 * shorter than the number of calls repeats its last entry, so "always 503" is
 * one line.
 */
export function scripted(replies: Reply[]): {
  fetch: typeof globalThis.fetch;
  calls: Call[];
} {
  const calls: Call[] = [];
  let index = 0;

  const impl = (async (url: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const reply = replies[Math.min(index, replies.length - 1)] ?? { status: 200, body: {} };
    index += 1;
    calls.push({
      method: init?.method ?? 'GET',
      url: url instanceof Request ? url.url : String(url),
      headers: { ...(init?.headers as Record<string, string>) },
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    });
    if (reply.throws) throw reply.throws;
    return new Response(reply.body === undefined ? '' : JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'Content-Type': 'application/json', ...reply.headers },
    });
  }) as typeof globalThis.fetch;

  return { fetch: impl, calls };
}

export function client(options: Partial<GraphRecOptions> = {}, fetchImpl?: typeof globalThis.fetch): GraphRec {
  return new GraphRec({
    apiKey: KEY,
    tenantId: TENANT,
    domain: 'graphrec.example',
    // Retries are exercised deliberately; sleeping for real would make the
    // suite slow enough that somebody would eventually shorten the budget
    // instead of the test.
    maxRetries: 0,
    ...(fetchImpl ? { fetch: fetchImpl } : {}),
    ...options,
  });
}

/** The envelope, as `graphrec/common/errors.py` renders it. */
export function envelope(
  cls: string,
  code: string,
  extra: Record<string, unknown> = {},
): { error: Record<string, unknown> } {
  return {
    error: {
      class: cls,
      code,
      reason: `copy for ${code}`,
      reference: 'ref-0001',
      field_errors: [],
      retryable: false,
      retry_after_seconds: null,
      ...extra,
    },
  };
}
