/**
 * Retry policy.
 *
 * The SDK retries only when doing so cannot duplicate a side effect:
 *
 * - Rate limiting (`429 rate_limit_exceeded`) and declared-retryable 503s are
 *   rejected before GraphRec changes anything, so every route may retry them.
 *   `Retry-After` / `retry_after_seconds` is honoured.
 * - Connection failures before the request was sent are always safe.
 * - Ambiguous failures (timeouts, dropped connections, 502/504 from a proxy)
 *   are retried only for idempotent routes: reads, upserts, and writes
 *   deduplicated by `event_id` or `Idempotency-Key`.
 *
 * `quota_exceeded` and every other 4xx are never retried.
 */
import { DEFAULT_MAX_RETRIES, INITIAL_RETRY_DELAY_MS, MAX_RETRY_AFTER_SECONDS, MAX_RETRY_DELAY_MS } from "./constants.js";
import { APIStatusError, APITimeoutError } from "./errors.js";
import type { Route } from "./routes.js";

export interface RetryOptions {
  maxRetries?: number;
  initialDelayMs?: number;
  maxDelayMs?: number;
  /** A server-requested wait longer than this (seconds) is surfaced as an error instead. */
  maxRetryAfterSeconds?: number;
  jitter?: number;
}

export class RetryPolicy {
  readonly maxRetries: number;
  readonly initialDelayMs: number;
  readonly maxDelayMs: number;
  readonly maxRetryAfterSeconds: number;
  readonly jitter: number;

  constructor(options: RetryOptions = {}) {
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.initialDelayMs = options.initialDelayMs ?? INITIAL_RETRY_DELAY_MS;
    this.maxDelayMs = options.maxDelayMs ?? MAX_RETRY_DELAY_MS;
    this.maxRetryAfterSeconds = options.maxRetryAfterSeconds ?? MAX_RETRY_AFTER_SECONDS;
    this.jitter = options.jitter ?? 0.25;
    if (this.maxRetries < 0) throw new RangeError("maxRetries must be >= 0");
  }

  /** Exponential backoff with jitter, in milliseconds, for zero-based `attempt`. */
  backoffMs(attempt: number): number {
    const base = Math.min(this.initialDelayMs * 2 ** attempt, this.maxDelayMs);
    const spread = base * this.jitter;
    return Math.max(0, base + (Math.random() * 2 - 1) * spread);
  }

  /** Milliseconds to wait before retrying `error`, or `null` to give up. */
  delayForStatus(error: APIStatusError, route: Route, attempt: number): number | null {
    if (attempt >= this.maxRetries) return null;
    if (error.code === "quota_exceeded") return null;
    const rejectedBeforeProcessing = error.status === 429 || (error.status === 503 && error.retryable);
    const gatewayFailure = (error.status === 502 || error.status === 504) && route.idempotent;
    if (!rejectedBeforeProcessing && !gatewayFailure) return null;
    if (error.retryAfterSeconds !== undefined) {
      if (error.retryAfterSeconds > this.maxRetryAfterSeconds) return null;
      return error.retryAfterSeconds * 1000;
    }
    return this.backoffMs(attempt);
  }

  /**
   * Milliseconds to wait before retrying a transport failure, or `null`.
   * `fetch` cannot tell a pre-send connection failure from a dropped
   * connection, so a non-timeout transport error is treated as ambiguous and
   * retried only on idempotent routes; timeouts likewise.
   */
  delayForTransport(error: unknown, route: Route, attempt: number): number | null {
    if (attempt >= this.maxRetries) return null;
    if (error instanceof APITimeoutError) return route.idempotent ? this.backoffMs(attempt) : null;
    if (isConnectionRefused(error) || route.idempotent) return this.backoffMs(attempt);
    return null;
  }
}

/** Errors Node's fetch raises before any bytes were sent (safe to retry on every route). */
function isConnectionRefused(error: unknown): boolean {
  const cause = (error as { cause?: { code?: string } } | undefined)?.cause;
  const code = cause?.code ?? (error as { code?: string } | undefined)?.code;
  // ECONNRESET is deliberately absent: the request may already have been processed.
  return code === "ECONNREFUSED" || code === "ENOTFOUND" || code === "EAI_AGAIN";
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
