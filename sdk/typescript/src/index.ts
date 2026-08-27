/**
 * `@graphrec/sdk` — call the GraphRec recommendation API from your own service.
 *
 * Server-side only, and that is a decision rather than an omission: the
 * credential is a bearer token with no origin binding, no expiry by default and
 * tenant-wide scope. Shipping it to a browser puts it in every visitor's
 * devtools. There is no browser build and there will not be one.
 *
 * The design this implements is `docs/SDK_DESIGN.md`.
 */

export { GraphRec } from './client.js';
export type { GraphRecOptions } from './config.js';
export { VERSION, normaliseTenantId } from './config.js';
export { Credential } from './credential.js';

export {
  AuthenticationError,
  ConfigurationError,
  ConflictError,
  GraphRecError,
  InternalError,
  LimitError,
  NotFoundError,
  PermissionError,
  QuotaExhaustedError,
  RateLimitedError,
  TimeoutError,
  TransportError,
  UnavailableError,
  ValidationError,
} from './errors.js';
export type { ErrorBody, ErrorClass, FieldError } from './errors.js';

export { SubmissionFailedError, SubmissionTimeoutError } from './resources/submissions.js';
export type { WaitOptions } from './resources/submissions.js';

export {
  MAX_CATEGORY,
  MAX_DATA_PLANE_ID,
  MAX_DESCRIPTION,
  MAX_EVENTS_PER_BATCH,
  MAX_EXCLUSIONS,
  MAX_EXTERNAL_ID,
  MAX_PRODUCTS_PER_SYNC,
  MAX_RECENT_EVENTS,
  MAX_TITLE,
  MAX_TOP_N,
} from './bounds.js';

export type {
  Availability,
  CallOptions,
  CatalogSyncInput,
  CustomerRecommendationRequest,
  EventBatchInput,
  EventInput,
  EventReceipt,
  EventType,
  FeedbackEvent,
  FeedbackRequest,
  FeedbackResponse,
  ModelVersion,
  ProductInput,
  RecentEvent,
  RecommendationResponse,
  RecommendedItem,
  SessionRecommendationRequest,
  Submission,
  SubmissionCounts,
  SubmissionErrorItem,
  SubmissionKind,
  SubmissionOutcome,
  SubmissionStage,
  SyncMode,
} from './types.js';
