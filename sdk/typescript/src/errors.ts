/**
 * The error hierarchy, one class per way a call can fail.
 *
 * Every failure the API produces has one shape — `graphrec/common/errors.py`
 * renders it, and `graphrec/http/errors.py` translates FastAPI's own 422s and
 * Starlette's bare HTTPExceptions into it too, so there is exactly one body to
 * parse. What this module adds is a *type* per failure, because `catch (e)` on a
 * single class means every caller re-implements the same `if (e.status === 429)`
 * ladder and gets one rung of it wrong.
 *
 * Two decisions are worth stating.
 *
 * **The subclass is chosen by `status` and `class` together, never by `class`
 * alone.** A 403 arrives as `class: "auth"` — `ForbiddenError` sets
 * `error_class = ErrorClass.AUTH` with `status_code = 403`. A client switching
 * on the class cannot tell "we do not know who you are" from "we know, and no",
 * which are the two failures with the most different remedies in the whole API.
 *
 * **`code` is a string and is deliberately not a union.** There are 87 of them
 * in `graphrec/common/error_copy.py` and the contract says `code` is additive.
 * Freezing the list into a type means a server that legally adds one produces a
 * value this package's own types call impossible.
 */

/** The seven the server can emit. There is no `forbidden`; a 403 is `auth`. */
export type ErrorClass =
  | 'validation'
  | 'conflict'
  | 'limit'
  | 'unavailable'
  | 'auth'
  | 'not_found'
  | 'internal';

export interface FieldError {
  field: string;
  reason: string;
}

/** The envelope, exactly as it arrives. `class` is a keyword, hence the quotes. */
export interface ErrorBody {
  class: ErrorClass;
  code: string;
  reason: string;
  reference: string;
  field_errors: FieldError[];
  retryable: boolean;
  retry_after_seconds: number | null;
}

export class GraphRecError extends Error {
  /** The stable machine-readable name of the failure. Switch on this. */
  readonly code: string;
  readonly errorClass: ErrorClass;
  /** Server-authored copy. Safe to show a user; it is vetted for this purpose. */
  readonly reason: string;
  /**
   * The traceable id. Quote it to support — it is the only thing that leads to
   * this exact request's log lines. Null only on a `TransportError`, which never
   * reached an application that could assign one.
   */
  readonly reference: string | null;
  readonly fieldErrors: FieldError[];
  readonly retryable: boolean;
  readonly retryAfterSeconds: number | null;
  readonly status: number | null;
  /** `X-Request-Id` off the response, which equals `reference` when both exist. */
  readonly requestId: string | null;

  constructor(
    message: string,
    init: {
      code: string;
      errorClass: ErrorClass;
      reason: string;
      reference: string | null;
      fieldErrors?: FieldError[];
      retryable?: boolean;
      retryAfterSeconds?: number | null;
      status?: number | null;
      requestId?: string | null;
      cause?: unknown;
    },
  ) {
    super(message, init.cause === undefined ? undefined : { cause: init.cause });
    this.name = new.target.name;
    this.code = init.code;
    this.errorClass = init.errorClass;
    this.reason = init.reason;
    this.reference = init.reference;
    this.fieldErrors = init.fieldErrors ?? [];
    this.retryable = init.retryable ?? false;
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
    this.status = init.status ?? null;
    this.requestId = init.requestId ?? null;
  }

  /**
   * Whether re-sending the *same* request could succeed.
   *
   * Both halves matter. `retryable` is the server saying the condition is
   * transient — `UnavailableError` and `InternalError` set it. A present
   * `retry_after_seconds` is the server naming a wait, which the rate limiter
   * does even though it reports `retryable: false`, because the request itself
   * was never wrong. A quota refusal has neither, and that is the distinction
   * this property exists to preserve: see `QuotaExhaustedError`.
   *
   * Whether it is *safe* to retry is a different question, answered by the
   * caller having supplied an idempotency identifier. `Transport` asks both.
   */
  get isTransient(): boolean {
    return this.retryable || this.retryAfterSeconds !== null;
  }
}

/** 422, and 413 when a bounded collection is oversize. Never retried. */
export class ValidationError extends GraphRecError {}

/** 409. Something in the tenant's state has to be reconciled first. */
export class ConflictError extends GraphRecError {}

/** 429. Never thrown directly — see the two subclasses. */
export class LimitError extends GraphRecError {}

/**
 * 429 `rate_limited`. Too many requests in the window; `retryAfterSeconds` is
 * the distance to the window edge and waiting it out works.
 */
export class RateLimitedError extends LimitError {}

/**
 * 429 `*_quota_exhausted`. The tenant's plan allowance for the period is spent.
 *
 * Also a 429, also `class: "limit"`, and the opposite remedy: there is no
 * `Retry-After` because waiting does not help — the quota resets at the end of
 * the billing period, and the fix is a plan change or an override. A client that
 * folded this into `RateLimitedError` would retry it until the period rolled.
 */
export class QuotaExhaustedError extends LimitError {}

/** 503. Transient by construction — `retryable` is true on the server class. */
export class UnavailableError extends GraphRecError {}

/** 401. The credential is absent, malformed, revoked or not ours. */
export class AuthenticationError extends GraphRecError {}

/**
 * 403. We know who you are and the answer is still no.
 *
 * Three codes reach here and they mean different things: `insufficient_scope`
 * (mint a credential with the scope), `insufficient_role` (a person's session
 * lacking the developer role) and `tenant_not_active` (the tenant is suspended
 * and no credential will work until that is resolved).
 */
export class PermissionError extends GraphRecError {}

/** 404, and it never names the resource — a foreign one and a missing one are one answer. */
export class NotFoundError extends GraphRecError {}

/** 500. Retryable, and the `reference` is what support needs. */
export class InternalError extends GraphRecError {}

/**
 * The request never got an answer: DNS, connect, TLS, socket.
 *
 * `reference` is null and says so, because no application assigned one. The
 * message names TLS explicitly: both public edges pin `protocols tls1.3`
 * (`deploy/n1/Caddyfile`, `deploy/n3/Caddyfile`), so a runtime that cannot
 * negotiate 1.3 fails the handshake with no status code to look up — and
 * "fetch failed" is not a diagnosis anybody can act on.
 */
export class TransportError extends GraphRecError {
  constructor(message: string, cause?: unknown) {
    super(message, {
      code: 'transport_error',
      errorClass: 'unavailable',
      reason: message,
      reference: null,
      retryable: true,
      cause,
    });
  }
}

/** The call's time budget ran out. Not retried — the budget is already spent. */
export class TimeoutError extends GraphRecError {
  constructor(message: string) {
    super(message, {
      code: 'timeout',
      errorClass: 'unavailable',
      reason: message,
      reference: null,
      retryable: false,
    });
  }
}

/** Bad SDK configuration, caught before a request is built. Never carries the credential. */
export class ConfigurationError extends GraphRecError {
  constructor(message: string) {
    super(message, {
      code: 'configuration_error',
      errorClass: 'validation',
      reason: message,
      reference: null,
    });
  }
}

/**
 * Starlette raises bare HTTPExceptions for a few transport-level conditions and
 * `graphrec/http/errors.py` maps them onto classes on the way out. The same map
 * is kept here for the reverse case: a response that is not an envelope at all —
 * a proxy's 502 HTML, a 413 from Caddy's `request_body` ceiling before the
 * application saw the request — still has to become a typed error.
 */
const STATUS_FALLBACK: Record<number, [ErrorClass, string]> = {
  400: ['validation', 'invalid_request'],
  401: ['auth', 'unauthenticated'],
  403: ['auth', 'insufficient_role'],
  404: ['not_found', 'not_found'],
  405: ['validation', 'invalid_request'],
  409: ['conflict', 'conflict'],
  413: ['validation', 'request_too_large'],
  422: ['validation', 'invalid_request'],
  429: ['limit', 'rate_limited'],
  500: ['internal', 'internal_error'],
  502: ['unavailable', 'service_unavailable'],
  503: ['unavailable', 'service_unavailable'],
  504: ['unavailable', 'service_unavailable'],
};

function looksLikeEnvelope(value: unknown): value is { error: ErrorBody } {
  if (typeof value !== 'object' || value === null) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as ErrorBody).code === 'string' &&
    typeof (error as ErrorBody).class === 'string'
  );
}

/** Which class the envelope becomes. Status first, because 403 hides inside `auth`. */
function classFor(status: number, body: ErrorBody): typeof GraphRecError {
  if (status === 401) return AuthenticationError;
  if (status === 403) return PermissionError;
  switch (body.class) {
    case 'validation':
      return ValidationError;
    case 'conflict':
      return ConflictError;
    case 'limit':
      // Same status, same class, opposite remedies. See `QuotaExhaustedError`.
      if (body.code === 'rate_limited') return RateLimitedError;
      if (body.code.endsWith('quota_exhausted')) return QuotaExhaustedError;
      return LimitError;
    case 'unavailable':
      return UnavailableError;
    case 'auth':
      return AuthenticationError;
    case 'not_found':
      return NotFoundError;
    case 'internal':
      return InternalError;
    default:
      return GraphRecError;
  }
}

/**
 * The message a stack trace will carry.
 *
 * `reason` is the server's copy, which is written for a person and is what a
 * caller should print. For a validation failure it is deliberately general —
 * "one or more fields were rejected" — and the part that says *which* lives in
 * `field_errors`. A stack trace that stops at the general half sends the reader
 * back to the API to find out what they already had, so the paths are appended
 * here. Three of them, then a count: this is a message, not a report, and the
 * full list is on the error.
 */
function summarise(reason: string, code: string, status: number, fields: FieldError[]): string {
  const head = reason || `${code} (${status})`;
  if (fields.length === 0) return head;
  const shown = fields.slice(0, 3).map((item) => `${item.field}: ${item.reason}`).join(', ');
  const more = fields.length > 3 ? `, and ${fields.length - 3} more` : '';
  return `${head} (${shown}${more})`;
}

/**
 * Build the typed error for a non-2xx response.
 *
 * `requestId` comes from the `X-Request-Id` header, which
 * `graphrec/http/middleware.py` sets on every response including ones that never
 * reached a handler. It becomes `reference` when the body carries none, so a
 * failure at the edge is still traceable.
 */
export function errorFrom(status: number, payload: unknown, requestId: string | null): GraphRecError {
  if (looksLikeEnvelope(payload)) {
    const body = payload.error;
    const Cls = classFor(status, body);
    const fieldErrors = body.field_errors ?? [];
    return new Cls(summarise(body.reason, body.code, status, fieldErrors), {
      code: body.code,
      errorClass: body.class,
      reason: body.reason,
      reference: body.reference ?? requestId,
      fieldErrors,
      retryable: body.retryable ?? false,
      retryAfterSeconds: body.retry_after_seconds ?? null,
      status,
      requestId,
    });
  }

  const [errorClass, code] = STATUS_FALLBACK[status] ?? ['internal', 'internal_error'];
  const Cls = classFor(status, {
    class: errorClass,
    code,
    reason: '',
    reference: '',
    field_errors: [],
    retryable: false,
    retry_after_seconds: null,
  });
  return new Cls(
    `The server answered ${status} with a body this client could not read as an error envelope.`,
    {
      code,
      errorClass,
      reason: '',
      reference: requestId,
      status,
      requestId,
      retryable: errorClass === 'unavailable' || errorClass === 'internal',
    },
  );
}
