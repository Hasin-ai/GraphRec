// Wire types for the GraphRec API (apps/api/routes/* and graphrec_core/schemas/*).

export interface ErrorBody {
  error?: {
    code?: string;
    message?: string;
    correlation_id?: string;
    retryable?: boolean;
    retry_after_seconds?: number;
    details?: { fields?: { field: string; message: string }[]; [key: string]: unknown };
  };
}

export class GraphRecApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId?: string;
  readonly retryAfterSeconds?: number;
  readonly fields: { field: string; message: string }[];
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ErrorBody | null, fallbackCorrelationId?: string) {
    super(body?.error?.message ?? "GraphRec could not process this request");
    this.name = "GraphRecApiError";
    this.status = status;
    this.code = body?.error?.code ?? (status === 0 ? "network_error" : "unknown_error");
    this.correlationId = body?.error?.correlation_id ?? fallbackCorrelationId;
    this.retryAfterSeconds = body?.error?.retry_after_seconds;
    this.fields = body?.error?.details?.fields ?? [];
    this.details = body?.error?.details ?? {};
  }
}

/** A limit change that would put a tenant below what it already stores (409 limit_below_usage). */
export interface LimitConflict { limit_name: string; limit: number; used: number; over_by: number; tenant_id?: string; tenant_name?: string }

// ── tenants / auth ─────────────────────────────────────────────
export interface TenantRegistrationInput {
  name: string;
  admin_email: string;
}

export interface TenantRegistrationResult {
  id: string;
  name: string;
  status: string;
  created_at: string;
  administrator_email: string;
  next_step: string;
  /** One-time account setup token; only the original 201 response carries it. */
  setup_token: string | null;
  setup_token_expires_at: string | null;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface SetupPasswordInput {
  setup_token: string;
  password: string;
  email?: string;
}

export interface RecoverPasswordInput {
  recovery_token: string;
  password: string;
  email?: string;
}

export type TenantUserRole = "tenant_administrator" | "tenant_developer";

export interface TenantUserResource {
  id: string;
  email: string;
  display_name: string;
  role: TenantUserRole;
  status: string;
  created_at: string;
  last_authenticated_at: string | null;
}
export interface TenantUserInvitation extends TenantUserResource {
  setup_token: string;
  setup_token_expires_at: string;
}

export interface AuthTokenPair {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  refresh_token: string;
  user_role: TenantUserRole;
  scopes: string[];
  /** Normalized sign-in email; labels the session when the client sent none. */
  email?: string | null;
}

// ── api keys ───────────────────────────────────────────────────
export type ApiKeyScope =
  | "billing:read"
  | "usage:read"
  | "catalog:read"
  | "catalog:write"
  | "events:read"
  | "events:write"
  | "training:read"
  | "training:write"
  | "models:read"
  | "models:write"
  | "models:deploy"
  | "recommendations:read"
  | "deployments:read"
  | "metrics:read";

export interface ApiKeyResource {
  id: string;
  name: string;
  prefix: string;
  scopes: ApiKeyScope[];
  status: "active" | "expired" | "revoked";
  expires_at: string | null;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  grace_expires_at: string | null;
}

export interface ApiKeySecretResource extends ApiKeyResource {
  secret: string;
}

export interface ApiKeyCreateInput {
  name: string;
  scopes: ApiKeyScope[];
  expires_at?: string | null;
}

export interface ApiKeyRotateInput {
  grace_period_seconds: number;
  reason: string;
}

// ── subscription / usage ───────────────────────────────────────
export interface SubscriptionResult {
  plan_code: "free" | "basic" | "pro";
  status: string;
  period_start: string;
  period_end: string;
  limits: Record<string, number>;
  project_defaults: boolean;
}

export type UsageType =
  | "accepted_events"
  | "recommendation_requests"
  | "training_jobs"
  | "training_cpu_seconds"
  | "stored_products"
  | "artifact_storage_bytes"
  | "active_model_versions"
  | "inference_replicas"
  | "replica_runtime_minutes";

export interface UsageDimension {
  type: UsageType;
  used: number;
  limit: number | null;
  remaining: number | null;
  unit: "count" | "seconds" | "bytes" | "minutes";
}

export interface UsageSummaryResult {
  period_start: string;
  period_end: string;
  reset_at: string;
  dimensions: UsageDimension[];
  last_reconciled_at: string;
  project_defaults: boolean;
}

// ── catalog ────────────────────────────────────────────────────
export interface ProductUpsert {
  external_id: string;
  title: string;
  description?: string | null;
  price?: number | string;
  category?: string | null;
  is_active?: boolean;
  availability_status?: string;
  metadata?: Record<string, unknown>;
}

export interface ProductBulkFailure {
  external_id: string;
  reason: string;
}

export interface ProductBulkUpsertResponse {
  sync_id?: string | null;
  status?: string;
  request_id?: string | null;
  accepted_count: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  rejected_count: number;
  failures: ProductBulkFailure[];
  outcomes?: { external_id: string; status: string; reason?: string }[];
}

export interface CatalogSyncResource extends ProductBulkUpsertResponse {
  sync_id: string;
  status: string;
  created_at: string;
}

export interface ProductResource {
  id: string;
  external_id: string;
  title: string;
  description?: string | null;
  price: number | string;
  category?: string | null;
  is_active: boolean;
  availability_status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProductListResponse {
  items: ProductResource[];
  total: number;
}

// ── events ─────────────────────────────────────────────────────
export interface EventSubmit {
  event_id: string;
  event_type: string;
  user_id?: string;
  external_product_id?: string;
  context?: Record<string, unknown>;
  occurred_at?: string;
}

export interface EventSubmitResponse {
  event_id: string;
  accepted: boolean;
  duplicate: boolean;
  received_at: string;
}

/** One stored interaction from GET /v1/events. */
export interface EventRecord {
  event_id: string;
  event_type: string;
  user_id?: string | null;
  external_product_id?: string | null;
  context: Record<string, unknown>;
  occurred_at: string;
  created_at: string;
}

export interface EventBatchResponse {
  id: string;
  status: string;
  request_id?: string | null;
  accepted_count: number;
  duplicate_count: number;
  rejected_count: number;
  outcomes?: { event_id: string; status: string; reason?: string }[];
  created_at: string;
}

// ── datasets ───────────────────────────────────────────────────
export interface DatasetSnapshotResource {
  id: string;
  tenant_id: string;
  training_job_id: string | null;
  cutoff_at: string;
  event_count: number;
  product_count: number;
  user_count: number;
  artifact_uri: string;
  checksum: string;
  created_at: string;
}

export interface DatasetUploadResponse {
  accepted_events: number;
  accepted_products: number;
  dataset_snapshot: DatasetSnapshotResource;
}

// ── models / training ──────────────────────────────────────────
export type ModelVersionStatus = "eligible" | "active" | "retired" | "archived" | string;

export interface ModelVersionResource {
  id: string;
  version_tag: string;
  model_type: string;
  status: ModelVersionStatus;
  metrics: Record<string, unknown>;
  artifact_uri: string | null;
  qdrant_collection: string | null;
  created_at: string;
  activated_at: string | null;
}

/** Training requests are durable; a separate worker advances the job. */
export type TrainingJobStatus = "queued" | "running" | "cancelling" | "cancelled" | "succeeded" | "failed" | string;

export interface TrainingJobCreate {
  request_id?: string;
  model_type?: string;
  dataset_snapshot_id?: string | null;
  configuration?: Record<string, unknown>;
}

export interface TrainingJobResource {
  progress: number;
  stage: string;
  cancel_requested: boolean;
  id: string;
  model_type: string;
  status: TrainingJobStatus;
  configuration: Record<string, unknown>;
  dataset_snapshot_id: string | null;
  model_version_id: string | null;
  qdrant_collection: string | null;
  failure_reason: string | null;
  created_at: string;
  completed_at: string | null;
}

// ── serving ────────────────────────────────────────────────────
/** D16: shared admission-control backend; "degraded" means Redis is unreachable and limits fail open per process. */
export interface RateLimiterStatus {
  backend: string;
  status: "ok" | "degraded" | "disabled" | string;
  fail_open_total: number;
  last_error_at: string | null;
}

export interface DeploymentStatus {
  id?: string | null;
  desired_model_version_id?: string | null;
  status: string;
  active_model_version_id: string | null;
  desired_capacity?: number;
  ready_capacity?: number;
  last_transition_at: string | null;
  failure_reason: string | null;
  rate_limiter?: RateLimiterStatus | null;
}

/** Offline measures recorded for the active version at training time. */
export interface QualitySummary {
  model_version_id: string;
  version_tag: string;
  recorded_at: string;
  /** Whatever the training run recorded; empty when it recorded none. */
  metrics: Record<string, unknown>;
}

/** Measured over the tenant's own requests in the window. */
export interface MetricsSummary {
  window_start: string;
  window_end: string;
  request_count: number;
  /** Requests per minute over the window. */
  request_rate: number;
  /** Null when no request was recorded: a rate over zero requests is undefined. */
  error_rate: number | null;
  fallback_rate: number | null;
  /** Null when no request was served successfully in the window. */
  p95_latency_ms: number | null;
  active_model_version_id: string | null;
  quality: QualitySummary | null;
}

// ── platform ───────────────────────────────────────────────────
export type PlatformTenantStatus = "active" | "suspended" | "deleting" | "deleted";

export interface PlatformTenant {
  id: string;
  slug: string;
  name: string;
  status: PlatformTenantStatus | string;
  created_at: string;
}

export interface PlatformPlan {
  warnings?: LimitConflict[];
  id: string;
  code: string;
  name: string;
  limits: Record<string, number>;
  is_active: boolean;
}

export interface PlatformQuotaOverride {
  warnings?: LimitConflict[];
  limits: Record<string, unknown>;
  overrides: Record<string, unknown>;
}

export interface PlatformFailure {
  id: string;
  tenant_id: string | null;
  event_type: string;
  severity: string;
  sanitized_detail: Record<string, unknown>;
  occurred_at: string;
}

export interface PlatformAudit {
  id: string;
  tenant_id: string;
  actor_type: string;
  action_type: string;
  resource_type: string;
  outcome: string;
  occurred_at: string;
}

export interface PlatformStatus {
  status: string;
  api_cluster: string;
  database: string;
  worker_pool: string;
  rate_limiter?: RateLimiterStatus | null;
  deployments?: { available_tenants: number; degraded_tenants: number; desired_capacity: number; ready_capacity: number } | null;
  timestamp: string;
}

// ── XR-F-02/03: retraining policy ─────────────────────────────
export interface RetrainingPolicyInput {
  schedule_enabled: boolean;
  interval_minutes: number;
  event_trigger_enabled: boolean;
  event_threshold: number;
  epochs: number;
}
export interface RetrainingPolicy extends RetrainingPolicyInput {
  tenant_id: string;
  configured: boolean;
  next_run_at: string | null;
  new_events_since_last_training: number;
  last_training_requested_at: string | null;
  training_in_progress: boolean;
  minimum_interval_minutes: number;
  last_evaluated_at: string | null;
  last_trigger: string | null;
  last_outcome: string | null;
  last_outcome_detail: string | null;
  last_outcome_at: string | null;
  last_job_id: string | null;
  updated_at: string | null;
}

// ── XR-F-04: recommendation rules ─────────────────────────────
export interface RecommendationPolicyInput {
  diversity_enabled: boolean;
  max_per_category: number;
  freshness_enabled: boolean;
  freshness_weight: number;
  freshness_half_life_days: number;
}
export interface RecommendationPolicy extends RecommendationPolicyInput {
  tenant_id: string;
  configured: boolean;
  version: number;
  updated_at: string | null;
}

// ── XR-F-07: usage trends ─────────────────────────────────────
export type TrendGranularity = "hour" | "day" | "week";
export interface UsageTrend {
  tenant_id: string;
  start: string;
  end: string;
  granularity: TrendGranularity;
  usage_types: string[];
  buckets: { start: string; values: Record<string, number> }[];
  totals: Record<string, number>;
}

// ── XR-F-08: serving capacity ─────────────────────────────────
export interface CapacityEvent {
  id: string;
  model_version_id: string | null;
  from_capacity: number;
  to_capacity: number;
  reason: string;
  measured_rpm: number;
  peak_rpm: number;
  max_capacity: number;
  occurred_at: string;
}
export interface ScalingStatus {
  managed: boolean;
  desired_capacity: number;
  ready_capacity: number;
  min_capacity: number;
  max_capacity: number;
  serving_slots: number | null;
  target_rpm_per_replica: number;
  scale_down_stabilization_seconds: number;
  measured_rpm: number;
  peak_rpm: number;
  last_scaled_at: string | null;
  events: CapacityEvent[];
  limitation: string;
}

// ── recommendations ────────────────────────────────────────────
export interface RecommendationResult {
  request_id: string;
  items: { external_product_id: string; position: number }[];
  /** Version that produced the ranking; null when a fallback served the request. */
  model_version_id: string | null;
  /** Active version at serving time, whether or not it served. */
  active_model_version_id?: string | null;
  strategy: string;
  fallback_used: boolean;
  fallback_tier: string;
  applied_rules: string[];
  rules_version: number | null;
}

/** `GET /v1/meta`: one product version shared by API, console and SDK. */
export interface ProductMeta {
  product: string;
  version: string;
  environment: "development" | "production";
  features: { development_placeholders: boolean };
}

/** `GET /v1/plans`: active plans and their current limits (public). */
export interface PublicPlan {
  code: string;
  name: string;
  limits: Record<string, number>;
}
