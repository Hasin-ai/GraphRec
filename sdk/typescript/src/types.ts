/**
 * The surface types, and the mapping to the wire.
 *
 * `camelCase` here, `snake_case` on the wire, converted in the resource modules.
 * Passing the wire shape through would have been less code and is the reason
 * this file exists: `snake_case` is idiomatic in neither TypeScript nor the
 * customer's own models, and once it leaks it leaks *unevenly* — the fields the
 * SDK touches get renamed and the ones it forwards do not, so a codebase ends up
 * with both spellings depending on which layer it is in.
 *
 * Field names, bounds and enum members below are taken from
 * `frontend/openapi.json` and from `graphrec/domain/ingestion/validation.py`,
 * which is where the per-item rules for bulk submissions actually live.
 */

// ---------------------------------------------------------------- enumerations

export type EventType = 'view' | 'add_to_cart' | 'purchase' | 'remove_from_cart';
export type Availability = 'in_stock' | 'low_stock' | 'out_of_stock';
export type SyncMode = 'upsert' | 'upsert_and_disable_missing';
export type SubmissionKind = 'product_sync' | 'event_batch';
/** The terminal-facing verdict. `processing` until the worker has finished. */
export type SubmissionOutcome = 'processing' | 'succeeded' | 'failed';
/** Where in the pipeline it is. Ordered; the console draws a rail from it. */
export type SubmissionStage = 'received' | 'validating' | 'applying' | 'completed' | 'failed';

// ---------------------------------------------------------------- data plane

export interface RecentEvent {
  externalProductId: string;
  eventType?: EventType;
  /** A `Date`, or an RFC 3339 string that carries an offset. */
  occurredAt?: Date | string;
}

interface RecommendationCommon {
  /**
   * Yours to choose, and the idempotency key for this call (`Ultimate` §27).
   *
   * It is also what ties a later impression, click or conversion back to the
   * answer that produced them, so keep it for as long as you keep the page.
   */
  requestId: string;
  topN?: number;
  recentEvents?: RecentEvent[];
  excludeProductIds?: string[];
  context?: Record<string, unknown>;
  /**
   * When `false`, a request that finds no ready model is refused `503
   * model_not_ready` instead of being served a popularity list.
   *
   * A product decision, not a transport one: it asks whether a generic answer is
   * worse than no answer on this surface. The SDK never sets it for you and
   * never retries past it.
   */
  allowFallback?: boolean;
}

export interface CustomerRecommendationRequest extends RecommendationCommon {
  customerId: string;
  sessionId?: string;
}

export interface SessionRecommendationRequest extends RecommendationCommon {
  sessionId: string;
}

export interface ModelVersion {
  versionId: string;
  versionNumber: number;
}

export interface RecommendedItem {
  externalProductId: string;
  rank: number;
  score: number;
  /** Which generator proposed it — useful when reading a fallback answer. */
  candidateSource: string;
}

export interface RecommendationResponse {
  requestId: string;
  /** Null when `fallbackApplied` is true: no model served this. */
  modelVersion: ModelVersion | null;
  strategy: string;
  fallbackApplied: boolean;
  items: RecommendedItem[];
  orderingPolicyVersion: number;
  latencyMs: number;
}

export interface FeedbackEvent {
  /** Yours, and the per-item idempotency key. An order line, a click id. */
  eventId: string;
  externalProductId: string;
  /**
   * A number here, unlike a catalogue event's `value`, which is a string.
   *
   * Not a mistake to correct in the SDK: the two planes model it differently
   * on purpose. `SubmitEventRequest.value` is a decimal string because it is
   * money a tenant may be billed against and a float cannot hold `129.00`
   * exactly; `FeedbackItemBody.value` is a float because it is a signal into a
   * ranking model. Papering over the difference would silently change one of
   * them.
   */
  value?: number;
}

export interface FeedbackRequest {
  /** The `requestId` of the recommendation these events are about. */
  requestId: string;
  events: FeedbackEvent[];
}

export interface FeedbackResponse {
  requestId: string;
  received: number;
  accepted: number;
  /** Events already reported under this `requestId`. A retry lands here. */
  duplicates: number;
  /** Identifiers that are not in your catalogue. Not an error; worth watching. */
  unknownProducts: string[];
}

// ------------------------------------------------------------- control plane

export interface EventInput {
  /** The idempotency key. Resending confirms the first rather than counting twice. */
  eventId: string;
  customerId: string;
  externalProductId: string;
  eventType: EventType;
  /**
   * A `Date`, or an RFC 3339 string **with an offset**.
   *
   * `parse_timestamp` refuses a naive timestamp rather than assuming UTC:
   * "2026-08-14 09:41" is a different instant in different places and guessing
   * would silently reorder a tenant's event history. Passing a `Date` makes this
   * impossible to get wrong, which is why the SDK accepts one.
   */
  occurredAt: Date | string;
  /** A decimal *string* — `"129.00"`. See `FeedbackEvent.value`. */
  value?: string;
  context?: Record<string, unknown>;
}

export interface EventReceipt {
  eventId: string;
  status: 'accepted' | 'duplicate_confirmed';
  /** Set only on `duplicate_confirmed`: when the first copy arrived. */
  firstReceivedAt: string | null;
}

export interface EventBatchInput {
  /** The collection's idempotency key. A repeat returns the original submission. */
  batchId: string;
  events: EventInput[];
}

export interface ProductInput {
  externalId: string;
  title: string;
  description?: string;
  category?: string;
  brand?: string;
  /** A decimal string or a number; sent as given. Money, so a string is safer. */
  price?: string | number;
  /** Defaults to `in_stock` server-side — a sync states the catalogue's contents. */
  availability?: Availability;
  /** Defaults to `true` server-side. */
  active?: boolean;
  attributes?: Record<string, unknown>;
}

export interface CatalogSyncInput {
  /** The collection's idempotency key. */
  syncId: string;
  products: ProductInput[];
  /**
   * `upsert_and_disable_missing` treats the payload as the whole catalogue and
   * disables anything absent from it. On a partial sync that empties a shop.
   */
  mode?: SyncMode;
}

export interface SubmissionCounts {
  /** `received === accepted + updated + skipped + failed`, always. */
  received: number;
  accepted: number;
  updated: number;
  /** Labelled "Duplicates" for an event batch and "Skipped" for a sync. */
  skipped: number;
  failed: number;
}

export interface SubmissionErrorItem {
  /** An identifier you sent, truncated. Never your payload echoed back. */
  ref: string;
  reason: string;
}

export interface Submission {
  submissionId: string;
  kind: SubmissionKind;
  status: SubmissionOutcome;
  stage: SubmissionStage;
  /** The `syncId` or `batchId` you chose. */
  reference: string;
  counts: SubmissionCounts;
  errors: SubmissionErrorItem[];
  errorCount: number;
  failureCode: string | null;
  submittedAt: string;
  completedAt: string | null;
}

// -------------------------------------------------------------------- shared

/** Per-call overrides. Every method takes one. */
export interface CallOptions {
  /** Overrides the client's budget for this call only. Milliseconds. */
  timeout?: number;
  signal?: AbortSignal;
  /**
   * Your own trace id, sent as `X-Request-Id`.
   *
   * `graphrec/http/middleware.py` echoes a supplied value (truncated to 64
   * characters) into every log line for the request and into the `reference` on
   * any error, which is what makes a support conversation about one specific
   * request possible.
   */
  requestId?: string;
}

/** An RFC 3339 instant with an offset, from a `Date` or a string. */
export function instant(value: Date | string): string {
  return value instanceof Date ? value.toISOString() : value;
}
