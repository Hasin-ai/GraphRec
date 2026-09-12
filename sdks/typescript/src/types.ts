/**
 * Wire types for the GraphRec API (`graphrec_core/schemas/*`). Response types
 * are open (`[key: string]: unknown` is implied by TypeScript structural
 * typing), so a newer server never breaks an older SDK.
 */

// ── enumerations ───────────────────────────────────────────────
export type EventType = "view" | "click" | "add_to_cart" | "remove_from_cart" | "purchase" | "rating" | "search" | "add_to_wishlist" | (string & {});
export type AvailabilityStatus = "available" | "unavailable" | "out_of_stock" | "discontinued" | (string & {});
export type ModelStatus = "eligible" | "active" | "retired" | "archived" | (string & {});
export type TrainingStatus = "queued" | "preparing_data" | "training" | "succeeded" | "failed" | "cancelled" | (string & {});
export type TenantStatus = "active" | "suspended" | "deleting" | "deleted";
export type ApiKeyStatus = "active" | "expired" | "revoked";
export type TenantUserRole = "tenant_administrator" | "tenant_developer";

export type Scope =
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
  | "metrics:read"
  | "keys:write";

export type ApiKeyScope = Exclude<Scope, "keys:write">;

/** Decimal money values travel as strings to avoid float rounding; numbers are accepted too. */
export type Money = string | number;
export type JsonObject = Record<string, unknown>;

// ── tenants & auth ─────────────────────────────────────────────
export interface TenantRegistrationInput {
  name: string;
  admin_email: string;
}

export interface TenantRegistration {
  id: string;
  name: string;
  status: string;
  created_at: string;
  administrator_email: string;
  next_step: string;
  /** One-time token for `auth.setupPassword`; `null` on an idempotent replay. */
  setup_token: string | null;
  setup_token_expires_at: string | null;
  /** `true` when the server replayed an earlier registration (HTTP 200 instead of 201). */
  replayed: boolean;
}

export interface TokenPair {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  refresh_token: string;
  user_role: TenantUserRole;
  scopes: string[];
}

// ── api keys ───────────────────────────────────────────────────
export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: ApiKeyScope[];
  status: ApiKeyStatus;
  expires_at: string | null;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  grace_expires_at: string | null;
}

export interface ApiKeyWithSecret extends ApiKey {
  /** Shown once. GraphRec stores only a hash. */
  secret: string;
}

export interface ApiKeyList {
  items: ApiKey[];
}

// ── billing ────────────────────────────────────────────────────
export interface Subscription {
  plan_code: string;
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

export interface UsageSummary {
  period_start: string;
  period_end: string;
  reset_at: string;
  dimensions: UsageDimension[];
  last_reconciled_at: string;
  project_defaults: boolean;
}

// ── catalog ────────────────────────────────────────────────────
export interface ProductInput {
  external_id: string;
  title: string;
  description?: string | null;
  price?: Money;
  category?: string | null;
  is_active?: boolean;
  availability_status?: AvailabilityStatus;
  metadata?: JsonObject;
}

export interface Product {
  id: string;
  external_id: string;
  title: string;
  description: string | null;
  price: string;
  category: string | null;
  is_active: boolean;
  availability_status: AvailabilityStatus;
  metadata: JsonObject;
  created_at: string;
  updated_at: string;
}

export interface ProductList {
  items: Product[];
  total: number;
}

export interface BulkUpsertFailure {
  external_id: string;
  reason: string;
}

export interface ProductBulkUpsertResult {
  accepted_count: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  rejected_count: number;
  failures: BulkUpsertFailure[];
  /** Number of HTTP requests the SDK made to apply the input. */
  request_count: number;
}

// ── events ─────────────────────────────────────────────────────
export interface EventInput {
  event_id?: string;
  event_type: EventType;
  user_id?: string | null;
  external_product_id?: string | null;
  context?: JsonObject;
  occurred_at?: string | Date;
}

/** An event with its identifier settled, as queued by the tracker and sent on the wire. */
export interface PreparedEvent {
  event_id: string;
  event_type: EventType;
  user_id?: string | null;
  external_product_id?: string | null;
  context: JsonObject;
  occurred_at?: string;
}

export interface EventReceipt {
  event_id: string;
  accepted: boolean;
  duplicate: boolean;
  received_at: string;
}

export interface EventBatch {
  id: string;
  status: string;
  accepted_count: number;
  duplicate_count: number;
  rejected_count: number;
  created_at: string;
}

export interface EventBatchResult {
  accepted_count: number;
  duplicate_count: number;
  rejected_count: number;
  /** Every batch the server created, one per request. */
  batches: EventBatch[];
  request_count: number;
}

// ── datasets ───────────────────────────────────────────────────
export interface DatasetSnapshot {
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

export interface DatasetSnapshotList {
  items: DatasetSnapshot[];
}

export interface DatasetUploadResult {
  accepted_events: number;
  accepted_products: number;
  dataset_snapshot: DatasetSnapshot;
}

// ── models & training ──────────────────────────────────────────
export interface ModelVersionInput {
  version_tag: string;
  model_type: string;
  metrics?: JsonObject;
  artifact_uri?: string | null;
}

export interface ModelVersion {
  id: string;
  version_tag: string;
  model_type: string;
  status: ModelStatus;
  metrics: JsonObject;
  artifact_uri: string | null;
  qdrant_collection: string | null;
  created_at: string;
  activated_at: string | null;
}

export interface ModelVersionList {
  items: ModelVersion[];
}

export interface TrainingJobInput {
  model_type?: string;
  dataset_snapshot_id?: string | null;
  configuration?: JsonObject;
}

export interface TrainingJob {
  id: string;
  model_type: string;
  status: TrainingStatus;
  configuration: JsonObject;
  dataset_snapshot_id: string | null;
  model_version_id: string | null;
  qdrant_collection: string | null;
  failure_reason: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface TrainingJobList {
  items: TrainingJob[];
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

export interface Replica {
  id: string;
  model_version_id: string | null;
  status: string;
  ready: boolean;
  started_at: string;
}

export interface ReplicaStatus {
  desired_replicas: number;
  current_replicas: number;
  ready_replicas: number;
  replicas: Replica[];
}

export interface ScalingAction {
  occurred_at: string;
  from_replicas: number;
  to_replicas: number;
  reason: string;
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
  recent_actions: ScalingAction[];
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

// ── recommendations & feedback ─────────────────────────────────
export interface RecommendationItem {
  external_product_id: string;
  position: number;
}

export interface Recommendations {
  request_id: string;
  items: RecommendationItem[];
  model_version_id: string | null;
  strategy: string;
  fallback_used: boolean;
  fallback_tier: string;
}

export interface FeedbackReceipt {
  event_id: string;
  feedback_type: string;
  accepted: boolean;
  duplicate: boolean;
  received_at: string;
}

// ── platform ───────────────────────────────────────────────────
export interface PlatformTenant {
  id: string;
  slug: string;
  name: string;
  status: TenantStatus | string;
  created_at: string;
}

export interface PlatformTenantList {
  items: PlatformTenant[];
}

export interface PricingPlan {
  id: string;
  code: string;
  name: string;
  limits: Record<string, unknown>;
  is_active: boolean;
}

export interface QuotaOverride {
  limits: Record<string, unknown>;
  overrides: Record<string, unknown>;
}

export interface PlatformFailure {
  id: string;
  tenant_id: string | null;
  event_type: string;
  severity: string;
  sanitized_detail: JsonObject;
  occurred_at: string;
}

export interface PlatformFailureList {
  items: PlatformFailure[];
}

export interface AuditRecord {
  id: string;
  tenant_id: string;
  actor_type: string;
  action_type: string;
  resource_type: string;
  outcome: string;
  occurred_at: string;
}

export interface AuditRecordList {
  items: AuditRecord[];
}

export interface PlatformStatus {
  status: string;
  api_cluster: string;
  database: string;
  worker_pool: string;
  timestamp: string;
}

export interface HealthStatus {
  status: string;
}
