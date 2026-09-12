/** Default API origin for the Docker Compose stack (`API_PORT` in `.env`). */
export const DEFAULT_BASE_URL = "http://localhost:8010";

/** Environment variables read when the matching constructor option is omitted. */
export const ENV_BASE_URL = "GRAPHREC_BASE_URL";
export const ENV_API_KEY = "GRAPHREC_API_KEY";
export const ENV_ACCESS_TOKEN = "GRAPHREC_ACCESS_TOKEN";

export const DEFAULT_TIMEOUT_MS = 30_000;
export const DEFAULT_MAX_RETRIES = 2;

/**
 * Mirrors the server's `MAX_REQUEST_BODY_BYTES` default (16 KiB). Bulk helpers
 * split payloads so that no single JSON request exceeds this many bytes.
 */
export const DEFAULT_MAX_BODY_BYTES = 16_384;

/** Upper bound on items per bulk request, independent of the byte budget. */
export const DEFAULT_MAX_BATCH_ITEMS = 500;

/** Longest server-suggested `Retry-After` the SDK will wait through automatically. */
export const MAX_RETRY_AFTER_SECONDS = 60;

export const INITIAL_RETRY_DELAY_MS = 500;
export const MAX_RETRY_DELAY_MS = 8_000;

/** Renew a password-based access token this many seconds before it expires. */
export const TOKEN_EXPIRY_SKEW_SECONDS = 30;

export const API_KEY_PREFIX = "gr_live_";

export const HEADER_CORRELATION_ID = "X-Correlation-ID";
export const HEADER_IDEMPOTENCY_KEY = "Idempotency-Key";

export const MAX_EVENT_ID_LENGTH = 100;
export const MAX_TOP_N = 100;
export const MAX_EXCLUSIONS = 200;
