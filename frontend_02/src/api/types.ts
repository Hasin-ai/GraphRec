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

  constructor(status: number, body: ErrorBody | null, fallbackCorrelationId?: string) {
    super(body?.error?.message ?? "GraphRec could not process this request");
    this.name = "GraphRecApiError";
    this.status = status;
    this.code = body?.error?.code ?? (status === 0 ? "network_error" : "unknown_error");
    this.correlationId = body?.error?.correlation_id ?? fallbackCorrelationId;
    this.retryAfterSeconds = body?.error?.retry_after_seconds;
    this.fields = body?.error?.details?.fields ?? [];
  }
}

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

export type TenantUserRole = "tenant_administrator" | "tenant_developer";

export interface AuthTokenPair {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  refresh_token: string;
  user_role: TenantUserRole;
  scopes: string[];
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
  accepted_count: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  rejected_count: number;
  failures: ProductBulkFailure[];
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

export interface EventBatchResponse {
  id: string;
  status: string;
  accepted_count: number;
  duplicate_count: number;
  rejected_count: number;
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

export type TrainingJobStatus =
  | "queued"
  | "preparing_data"
  | "training"
  | "succeeded"
  | "failed"
  | string;

export interface TrainingJobCreate {
  model_type?: string;
  dataset_snapshot_id?: string | null;
  configuration?: Record<string, unknown>;
}

export interface TrainingJobResource {
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
export interface DeploymentStatus {
  status: string;
  active_model_version_id: string | null;
  desired_model_version_id: string | null;
  desired_replicas: number;
  current_replicas: number;
  ready_replicas: number;
  last_transition_at: string;
  failure_reason: string | null;
}

export interface ReplicaItem {
  id: string;
  model_version_id: string | null;
  status: string;
  ready: boolean;
  started_at: string;
}

export interface ReplicaStatusResponse {
  desired_replicas: number;
  current_replicas: number;
  ready_replicas: number;
  replicas: ReplicaItem[];
}

export interface AutoscalingStatus {
  min_replicas: number;
  max_replicas: number;
  cpu_target_percent: number;
  inflight_target: number | null;
  desired_replicas: number;
  ready_replicas: number;
  capacity_blocked: boolean;
  metrics_available: boolean;
  recent_actions: { occurred_at: string; from_replicas: number; to_replicas: number; reason: string }[];
}

export interface QualitySummary {
  hit_at_10: number;
  ndcg_at_10: number;
  retrieval_recall_at_k: number;
  catalog_coverage: number;
  intra_list_diversity: number;
  training_loss: number;
  validation_loss: number;
  recorded_at: string;
}

export interface MetricsSummary {
  window_start: string;
  window_end: string;
  request_rate: number;
  error_rate: number;
  fallback_rate: number;
  p95_latency_ms: number;
  active_model_version_id: string | null;
  desired_replicas: number;
  ready_replicas: number;
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
  id: string;
  code: string;
  name: string;
  limits: Record<string, unknown>;
  is_active: boolean;
}

export interface PlatformQuotaOverride {
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
  timestamp: string;
}
