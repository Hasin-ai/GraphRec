/**
 * Error hierarchy for the GraphRec SDK. Every error derives from `GraphRecError`.
 *
 * GraphRec returns failures in a stable envelope:
 *
 *     {"error": {"code": "rate_limit_exceeded", "message": "...", "correlation_id": "…",
 *                "retryable": true, "retry_after_seconds": 12, "details": {...}}}
 *
 * `errorFromResponse` maps that envelope onto the most specific subclass so
 * callers can write `if (e instanceof NotFoundError)` instead of inspecting
 * status codes. `correlationId` matches the `X-Correlation-ID` GraphRec logs.
 */

export class GraphRecError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

/** The client is not configured for the requested call (e.g. missing credentials). */
export class ConfigurationError extends GraphRecError {}

/** Arguments failed client-side validation before any request was sent. */
export class InputValidationError extends GraphRecError {}

/** A polling helper such as `trainingJobs.wait()` gave up before completion. */
export class WaitTimeoutError extends GraphRecError {}

export interface RequestInfoSummary {
  method: string;
  url: string;
}

/** A request reached (or tried to reach) the GraphRec API and failed. */
export class APIError extends GraphRecError {
  readonly request?: RequestInfoSummary;
  readonly correlationId?: string;
  /** Set by bulk helpers: totals applied by the requests that succeeded before this failure. */
  partialResult?: unknown;

  constructor(message: string, options: { request?: RequestInfoSummary; correlationId?: string } = {}) {
    super(message);
    this.request = options.request;
    this.correlationId = options.correlationId;
  }
}

/** The API could not be reached (DNS, refused connection, TLS, reset...). */
export class APIConnectionError extends APIError {
  constructor(message = "Could not connect to the GraphRec API", options: { request?: RequestInfoSummary; cause?: unknown } = {}) {
    super(message, { request: options.request });
    if (options.cause !== undefined) (this as { cause?: unknown }).cause = options.cause;
  }
}

/** The request timed out. */
export class APITimeoutError extends APIConnectionError {
  constructor(message = "The GraphRec API request timed out", options: { request?: RequestInfoSummary } = {}) {
    super(message, options);
  }
}

export interface FieldError {
  field: string;
  message: string;
}

export interface StatusErrorOptions {
  status: number;
  code: string;
  request?: RequestInfoSummary;
  correlationId?: string;
  retryable?: boolean;
  retryAfterSeconds?: number;
  details?: Record<string, unknown>;
  body?: unknown;
}

/** The API answered with a non-success HTTP status. */
export class APIStatusError extends APIError {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly retryAfterSeconds?: number;
  readonly details: Record<string, unknown>;
  readonly body: unknown;

  constructor(message: string, options: StatusErrorOptions) {
    super(message, { request: options.request, correlationId: options.correlationId });
    this.status = options.status;
    this.code = options.code;
    this.retryable = options.retryable ?? false;
    this.retryAfterSeconds = options.retryAfterSeconds;
    this.details = options.details ?? {};
    this.body = options.body;
  }

  override toString(): string {
    const suffix = this.correlationId ? ` (correlation_id=${this.correlationId})` : "";
    return `${this.status} ${this.code}: ${this.message}${suffix}`;
  }
}

/** HTTP 400 `malformed_request` - headers or JSON body were rejected. */
export class MalformedRequestError extends APIStatusError {}
/** HTTP 401 - the credential is missing, invalid, revoked or expired. */
export class AuthenticationError extends APIStatusError {}
/** HTTP 401 `token_expired` - the bearer access token has expired. */
export class TokenExpiredError extends AuthenticationError {}
/** HTTP 403 `insufficient_scope` - the credential lacks a required scope. */
export class PermissionDeniedError extends APIStatusError {}
/** HTTP 404 `resource_not_found`. */
export class NotFoundError extends APIStatusError {}
/** HTTP 409 - base class for conflicts. */
export class ConflictError extends APIStatusError {}
/** HTTP 409 `duplicate_resource` - e.g. an API-key name or version tag is taken. */
export class DuplicateResourceError extends ConflictError {}
/** HTTP 409 `idempotency_conflict` - an Idempotency-Key was reused with a new body. */
export class IdempotencyConflictError extends ConflictError {}
/** HTTP 409 `state_conflict` / `conflict` - the resource is in the wrong state. */
export class StateConflictError extends ConflictError {}
/** HTTP 413 `payload_too_large` - the body exceeded the server's limit. */
export class PayloadTooLargeError extends APIStatusError {}
/** HTTP 422 `validation_failed` - one or more fields are invalid. */
export class RequestValidationError extends APIStatusError {
  get fieldErrors(): FieldError[] {
    const fields = this.details.fields;
    if (!Array.isArray(fields)) return [];
    return fields
      .filter((f): f is Record<string, unknown> => !!f && typeof f === "object")
      .map((f) => ({ field: String(f.field ?? ""), message: String(f.message ?? "") }));
  }
}
/** HTTP 429 `rate_limit_exceeded` - retry after `retryAfterSeconds`. */
export class RateLimitError extends APIStatusError {}
/** HTTP 429 `quota_exceeded` - a plan or tenant quota is exhausted (not retryable). */
export class QuotaExceededError extends APIStatusError {}
/** HTTP 5xx without a more specific code. */
export class InternalServerError extends APIStatusError {}
/** HTTP 503 `service_unavailable` - a dependency is temporarily unavailable. */
export class ServiceUnavailableError extends InternalServerError {}

/** A success response did not match the shape the SDK expects. */
export class APIResponseValidationError extends APIError {
  readonly status: number;
  readonly body: unknown;
  constructor(message: string, options: { status: number; body: unknown; request?: RequestInfoSummary; correlationId?: string }) {
    super(message, { request: options.request, correlationId: options.correlationId });
    this.status = options.status;
    this.body = options.body;
  }
}

type StatusErrorCtor = new (message: string, options: StatusErrorOptions) => APIStatusError;

const CODE_MAP: Record<string, StatusErrorCtor> = {
  malformed_request: MalformedRequestError,
  authentication_failed: AuthenticationError,
  invalid_setup_token: AuthenticationError,
  token_expired: TokenExpiredError,
  insufficient_scope: PermissionDeniedError,
  resource_not_found: NotFoundError,
  duplicate_resource: DuplicateResourceError,
  idempotency_conflict: IdempotencyConflictError,
  state_conflict: StateConflictError,
  conflict: StateConflictError,
  payload_too_large: PayloadTooLargeError,
  validation_failed: RequestValidationError,
  rate_limit_exceeded: RateLimitError,
  quota_exceeded: QuotaExceededError,
  service_unavailable: ServiceUnavailableError,
};

const STATUS_MAP: Record<number, StatusErrorCtor> = {
  400: MalformedRequestError,
  401: AuthenticationError,
  403: PermissionDeniedError,
  404: NotFoundError,
  409: ConflictError,
  413: PayloadTooLargeError,
  422: RequestValidationError,
  429: RateLimitError,
  503: ServiceUnavailableError,
};

function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** Build the most specific `APIStatusError` for an error response. */
export function errorFromResponse(response: Response, body: unknown, request?: RequestInfoSummary): APIStatusError {
  const envelope: Record<string, unknown> = isRecord(body) && isRecord(body.error) ? body.error : {};
  const status = response.status;
  const code = String(envelope.code || `http_${status}`);
  const message = String(envelope.message || response.statusText || `HTTP ${status} from GraphRec API`);
  const correlationId = envelope.correlation_id ?? response.headers.get("X-Correlation-ID") ?? undefined;
  const retryAfterRaw = envelope.retry_after_seconds;
  const retryAfterSeconds = typeof retryAfterRaw === "number" ? retryAfterRaw : parseRetryAfter(response.headers.get("Retry-After"));
  let retryable = typeof envelope.retryable === "boolean" ? envelope.retryable : status === 429 || status === 503;
  if (code === "quota_exceeded") retryable = false;
  const details = isRecord(envelope.details) ? envelope.details : undefined;

  const ctor = CODE_MAP[code] ?? STATUS_MAP[status] ?? (status >= 500 ? InternalServerError : APIStatusError);
  return new ctor(message, {
    status,
    code,
    request,
    correlationId: correlationId ? String(correlationId) : undefined,
    retryable,
    retryAfterSeconds,
    details,
    body,
  });
}
