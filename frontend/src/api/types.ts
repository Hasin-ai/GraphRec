export interface TenantRegistrationInput {
  name: string;
  admin_email: string;
}

export interface TenantRegistrationResult {
  id: string;
  name: string;
  status: "active";
  created_at: string;
  administrator_email: string;
  next_step: string;
}

export interface LoginInput {
  email: string;
  password: string;
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

export interface ApiKeyListResult {
  items: ApiKeyResource[];
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

interface ErrorBody {
  error?: {
    code?: string;
    message?: string;
    correlation_id?: string;
    retryable?: boolean;
    retry_after_seconds?: number;
  };
}

export class GraphRecApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId?: string;
  readonly retryAfterSeconds?: number;

  constructor(status: number, body: ErrorBody, fallbackCorrelationId?: string) {
    super(body.error?.message ?? "GraphRec could not process this request");
    this.name = "GraphRecApiError";
    this.status = status;
    this.code = body.error?.code ?? "unknown_error";
    this.correlationId = body.error?.correlation_id ?? fallbackCorrelationId;
    this.retryAfterSeconds = body.error?.retry_after_seconds;
  }
}

export interface ProductUpsert {
  external_id: string;
  title: string;
  description?: string;
  price?: number;
  category?: string;
  is_active?: boolean;
  availability_status?: string;
  metadata?: Record<string, unknown>;
}

export interface ProductBulkUpsertRequest {
  products: ProductUpsert[];
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
  description?: string;
  price: number;
  category?: string;
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

export interface EventSubmit {
  event_id: string;
  event_type: string;
  user_id?: string;
  external_product_id?: string;
  context?: Record<string, unknown>;
  occurred_at?: string;
}

export interface EventBatchSubmit {
  events: EventSubmit[];
}

export interface EventBatchResponse {
  id: string;
  status: string;
  accepted_count: number;
  duplicate_count: number;
  rejected_count: number;
  created_at: string;
}

export interface ModelVersionCreate {
  version_tag: string;
  model_type: string;
  metrics?: Record<string, unknown>;
  artifact_uri?: string;
}

export interface ModelVersionResource {
  id: string;
  version_tag: string;
  model_type: string;
  status: "active" | "eligible" | "retired" | "archived";
  metrics: Record<string, number>;
  artifact_uri?: string;
  created_at: string;
  activated_at?: string;
}

export interface ModelVersionListResponse {
  items: ModelVersionResource[];
}

export interface TrainingJobCreate {
  model_type?: string;
  dataset_snapshot_id?: string;
  configuration?: Record<string, unknown>;
}

export interface TrainingJobResource {
  id: string;
  model_type: string;
  status: "queued" | "preparing_data" | "training" | "succeeded" | "failed";
  configuration: Record<string, unknown>;
  dataset_snapshot_id?: string;
  model_version_id?: string;
  failure_reason?: string;
  created_at: string;
  completed_at?: string;
}

export interface TrainingJobListResponse {
  items: TrainingJobResource[];
}

