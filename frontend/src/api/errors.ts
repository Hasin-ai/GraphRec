/**
 * The error envelope, as the backend defines it in `graphrec/common/errors.py`.
 *
 * Every failure the API produces has this shape, and the console never invents
 * copy of its own for one: `reason` is resolved server-side from
 * `graphrec/common/error_copy.py`, so what the user reads here is the same
 * sentence a direct API caller reads. That is the point of the catalogue — the
 * console and the API cannot drift into saying different things about the same
 * refusal.
 */

export type ErrorClass =
  | 'validation'
  | 'conflict'
  | 'limit'
  | 'unavailable'
  | 'auth'
  | 'forbidden'
  | 'not_found'
  | 'internal';

export interface FieldError {
  field: string;
  reason: string;
}

export interface ErrorBody {
  class: ErrorClass;
  code: string;
  reason: string;
  /** The traceable reference §10 requires a failure to carry. */
  reference: string;
  field_errors: FieldError[];
  retryable: boolean;
  retry_after_seconds: number | null;
}

/**
 * What every non-2xx response becomes. It is an `Error` so it can be thrown
 * through a react-router loader and caught by an error boundary, and it keeps
 * the envelope intact so the boundary can decide by `status` and the form can
 * decide by `field_errors`.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly body: ErrorBody;

  constructor(status: number, body: ErrorBody) {
    super(body.reason || `Request failed with ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }

  get code(): string {
    return this.body.code;
  }

  get reference(): string {
    return this.body.reference;
  }

  /** Field errors keyed by field name, for a form to attach to its inputs. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const item of this.body.field_errors ?? []) {
      // A nested field arrives as `limits.training_limit`; forms are flat, so
      // the last segment is what an input is named after. First writer wins,
      // so the outermost error is the one shown.
      const key = item.field.split('.').pop() ?? item.field;
      if (!(key in out)) out[key] = item.reason;
    }
    return out;
  }
}

/**
 * Builds an `ApiError` from a response whose body may not be an envelope at
 * all — a proxy 502, an HTML error page, a network-level truncation. Those are
 * real and a console that assumed the envelope would throw a `TypeError` from
 * inside its own error handling.
 */
export async function toApiError(response: Response): Promise<ApiError> {
  let body: ErrorBody | undefined;
  try {
    const parsed: unknown = await response.json();
    if (parsed && typeof parsed === 'object' && 'error' in parsed) {
      body = (parsed as { error: ErrorBody }).error;
    }
  } catch {
    body = undefined;
  }
  // §10.3: capture `X-Request-Id` and use it as the reference. The application
  // puts its own reference in the envelope; this covers the failures that never
  // reached the application — a proxy 502, a gateway timeout — where the header
  // is the only thing anyone can trace.
  const requestId = response.headers.get('X-Request-Id');
  if (body && requestId && !body.reference) body = { ...body, reference: requestId };
  return new ApiError(
    response.status,
    body ?? {
      class: response.status >= 500 ? 'internal' : 'unavailable',
      code: 'unexpected_response',
      reason:
        'The service returned something this console could not read. ' +
        'Try again; if it persists, quote the status code below.',
      reference: requestId ?? `http-${response.status}`,
      field_errors: [],
      retryable: response.status >= 500,
      retry_after_seconds: null,
    },
  );
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
