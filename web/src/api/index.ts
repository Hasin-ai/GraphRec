import { request } from "./client";
import type {
  ApiKeyCreateInput,
  ApiKeyResource,
  ApiKeyRotateInput,
  ApiKeySecretResource,
  AuthTokenPair,
  DatasetSnapshotResource,
  DatasetUploadResponse,
  DeploymentStatus,
  EventBatchResponse,
  EventRecord,
  EventSubmit,
  EventSubmitResponse,
  LoginInput,
  MetricsSummary,
  ModelVersionResource,
  PlatformAudit,
  PlatformTenantUsage,
  TenantAuditItem,
  PlatformFailure,
  PlatformPlan,
  PlatformQuotaOverride,
  PlatformStatus,
  PlatformTenant,
  PlatformTenantStatus,
  ProductBulkUpsertResponse,
  CatalogSyncResource,
  ProductListResponse,
  ProductResource,
  ProductUpsert,
  SetupPasswordInput,
  RecoverPasswordInput,
  SubscriptionResult,
  TenantRegistrationInput,
  TenantRegistrationResult,
  TrainingJobCreate,
  TrainingJobResource,
  UsageSummaryResult,
  TenantUserResource,
  TenantUserInvitation,
  TenantUserRole,
  RetrainingPolicy,
  RetrainingPolicyInput,
  RecommendationPolicy,
  RecommendationPolicyInput,
  UsageTrend,
  TrendGranularity,
  ScalingStatus,
  RecommendationResult,
  ProductMeta,
  PublicPlan,
  OperatorSession,
  PlatformOperator,
  PlatformMe,
  TenantStatus,
} from "./types";

const enc = encodeURIComponent;

/** Body fragment for an optional audit reason (omitted when blank). */
function reasonBody(reason: string | undefined): { reason?: string } {
  const trimmed = reason?.trim();
  return trimmed ? { reason: trimmed } : {};
}

/** Optional lifecycle-action body carrying an audit reason (ER-F-11). */
function withReason(reason?: string): { json?: { reason: string } } {
  const trimmed = reason?.trim();
  return trimmed ? { json: { reason: trimmed } } : {};
}

export const tenantStatus = {
  get: () => request<TenantStatus>("/v1/tenant/status"),
};

export const meta = {
  get: () => request<ProductMeta>("/v1/meta", { realm: "public" }),
  plans: () => request<{ items: PublicPlan[] }>("/v1/plans", { realm: "public" }),
};

export const tenantUsers = {
  list: () => request<{ items: TenantUserResource[]; total: number }>("/v1/tenant/users"),
  invite: (input: { email: string; display_name?: string; role: TenantUserRole }) =>
    request<TenantUserInvitation>("/v1/tenant/users", { method: "POST", json: input }),
  revokeInvitation: (id: string) => request<TenantUserResource>(`/v1/tenant/users/${enc(id)}/invitation`, { method: "DELETE" }),
  /** UC-27: change role or status; ends the member's sessions. */
  update: (id: string, change: { role?: TenantUserRole; status?: "active" | "locked" | "disabled"; reason?: string }) =>
    request<TenantUserResource>(`/v1/tenant/users/${enc(id)}`, { method: "PATCH", json: change }),
  resendInvitation: (id: string) => request<TenantUserInvitation>(`/v1/tenant/users/${enc(id)}/invitation:resend`, { method: "POST" }),
};

// ── public ─────────────────────────────────────────────────────
export const auth = {
  login: (input: LoginInput) =>
    request<AuthTokenPair>("/v1/auth/login", { method: "POST", json: input, realm: "public" }),
  setupPassword: (input: SetupPasswordInput) =>
    request<AuthTokenPair>("/v1/auth/setup-password", { method: "POST", json: input, realm: "public" }),
  recoverPassword: (input: RecoverPasswordInput) =>
    request<{ status: string }>("/v1/auth/recover-password", { method: "POST", json: input, realm: "public" }),
  registerTenant: (input: TenantRegistrationInput, idempotencyKey: string) =>
    request<TenantRegistrationResult>("/v1/tenants", {
      method: "POST",
      json: input,
      realm: "public",
      headers: { "Idempotency-Key": idempotencyKey },
    }),
};

// ── tenant ─────────────────────────────────────────────────────
export const apiKeys = {
  list: () => request<{ items: ApiKeyResource[] }>("/v1/api-keys"),
  get: (id: string) => request<ApiKeyResource>(`/v1/api-keys/${enc(id)}`),
  create: (input: ApiKeyCreateInput) =>
    request<ApiKeySecretResource>("/v1/api-keys", { method: "POST", json: input }),
  rotate: (id: string, input: ApiKeyRotateInput) =>
    request<ApiKeySecretResource>(`/v1/api-keys/${enc(id)}/rotate`, { method: "POST", json: input }),
  revoke: (id: string) => request<ApiKeyResource>(`/v1/api-keys/${enc(id)}`, { method: "DELETE" }),
};

export const billing = {
  subscription: () => request<SubscriptionResult>("/v1/subscription"),
  usage: () => request<UsageSummaryResult>("/v1/usage"),
  /** XR-F-07: ledger sums per bucket. `start`/`end` are ISO-8601 with offset. */
  trends: (params: { granularity: TrendGranularity; start?: string; end?: string; types?: string[] }) => {
    const query = new URLSearchParams({ granularity: params.granularity });
    if (params.start) query.set("start", params.start);
    if (params.end) query.set("end", params.end);
    if (params.types?.length) query.set("types", params.types.join(","));
    return request<UsageTrend>(`/v1/usage/trends?${query.toString()}`);
  },
};

export const retraining = {
  get: () => request<RetrainingPolicy>("/v1/retraining-policy"),
  put: (input: RetrainingPolicyInput) => request<RetrainingPolicy>("/v1/retraining-policy", { method: "PUT", json: input }),
};

/** Live recommendations. Each call counts toward the recommendation_requests quota. */
export const recommendations = {
  get: (input: { user_id?: string; top_n?: number; context?: Record<string, unknown> }) =>
    request<RecommendationResult>("/v1/recommendations", { method: "POST", json: input }),
};

export const recommendationRules = {
  get: () => request<RecommendationPolicy>("/v1/recommendation-policy"),
  put: (input: RecommendationPolicyInput) => request<RecommendationPolicy>("/v1/recommendation-policy", { method: "PUT", json: input }),
};

export const products = {
  /** One page (server default 500, max 1000) or specific ids (at most 200). `total` counts every match. */
  list: (params: { limit?: number; offset?: number; ids?: string[] } = {}) => {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    if (params.ids?.length) query.set("ids", params.ids.join(","));
    const suffix = query.toString();
    return request<ProductListResponse>(`/v1/products${suffix ? `?${suffix}` : ""}`);
  },
  get: (externalId: string) => request<ProductResource>(`/v1/products/${enc(externalId)}`),
  put: (externalId: string, input: ProductUpsert) =>
    request<ProductResource>(`/v1/products/${enc(externalId)}`, { method: "PUT", json: input }),
  disable: (externalId: string) =>
    request<ProductResource>(`/v1/products/${enc(externalId)}:disable`, { method: "POST" }),
  bulkUpsert: (items: ProductUpsert[], requestId?: string) =>
    request<ProductBulkUpsertResponse>("/v1/products:bulk-upsert", { method: "POST", json: { products: items, ...(requestId ? { request_id: requestId } : {}) } }),
  listSyncs: () => request<CatalogSyncResource[]>("/v1/catalog-syncs"),
  getSync: (id: string) => request<CatalogSyncResource>(`/v1/catalog-syncs/${enc(id)}`),
};

export const events = {
  submit: (input: EventSubmit) => request<EventSubmitResponse>("/v1/events", { method: "POST", json: input }),
  submitBatch: (items: EventSubmit[], requestId?: string) =>
    request<EventBatchResponse>("/v1/events/batches", { method: "POST", json: { events: items, ...(requestId ? { request_id: requestId } : {}) } }),
  list: (filter: { limit?: number; user_id?: string; event_type?: string; external_product_id?: string } = {}) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(filter)) if (v !== undefined && v !== "") q.set(k, String(v));
    const qs = q.toString();
    return request<EventRecord[]>(`/v1/events${qs ? `?${qs}` : ""}`);
  },
  listBatches: () => request<EventBatchResponse[]>("/v1/events/batches"),
  getBatch: (id: string) => request<EventBatchResponse>(`/v1/events/batches/${enc(id)}`),
};

export const datasets = {
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DatasetUploadResponse>("/v1/datasets/upload", { method: "POST", form });
  },
  listSnapshots: () => request<{ items: DatasetSnapshotResource[] }>("/v1/datasets/snapshots"),
  getSnapshot: (id: string) => request<DatasetSnapshotResource>(`/v1/datasets/snapshots/${enc(id)}`),
  createSnapshot: (input: { cutoff_at?: string | null }) =>
    request<DatasetSnapshotResource>("/v1/datasets/snapshots", { method: "POST", json: input }),
};

export const models = {
  list: () => request<{ items: ModelVersionResource[] }>("/v1/model-versions"),
  get: (id: string) => request<ModelVersionResource>(`/v1/model-versions/${enc(id)}`),
  activate: (id: string, reason?: string) =>
    request<ModelVersionResource>(`/v1/model-versions/${enc(id)}:activate`, { method: "POST", ...withReason(reason) }),
  archive: (id: string, reason?: string) =>
    request<ModelVersionResource>(`/v1/model-versions/${enc(id)}:archive`, { method: "POST", ...withReason(reason) }),
  rollback: (targetId: string, reason?: string) =>
    request<ModelVersionResource>(`/v1/model-versions/${enc(targetId)}:rollback`, { method: "POST", ...withReason(reason) }),
};

export const training = {
  cancel: (id: string, reason?: string) => request<TrainingJobResource>(`/v1/training-jobs/${encodeURIComponent(id)}:cancel`, { method: "POST", ...withReason(reason) }),
  get: (id: string) => request<TrainingJobResource>(`/v1/training-jobs/${enc(id)}`),
  list: () => request<{ items: TrainingJobResource[] }>("/v1/training-jobs"),
  create: (input: TrainingJobCreate) =>
    request<TrainingJobResource>("/v1/training-jobs", { method: "POST", json: input }),
};

export const serving = {
  deployment: () => request<DeploymentStatus>("/v1/deployment"),
  scaling: () => request<ScalingStatus>("/v1/deployment/scaling"),
  /** Measured over the last `windowMinutes` (the API defaults to 60). */
  metrics: (windowMinutes?: number) =>
    request<MetricsSummary>(
      windowMinutes === undefined ? "/v1/metrics/summary" : `/v1/metrics/summary?window_minutes=${windowMinutes}`,
    ),
};

// ── platform ───────────────────────────────────────────────────
const platformRealm = { realm: "platform" as const };

export const platform = {
  getTenantQuota: (id: string) => request<PlatformQuotaOverride & { plan_id: string; plan_code: string }>(`/v1/platform/tenants/${enc(id)}/quotas`, platformRealm),
  getTenantUsage: (id: string) => request<UsageSummaryResult>(`/v1/platform/tenants/${enc(id)}/usage`, platformRealm),
  issueRecovery: (id: string, email: string, reason?: string) => request<{ recovery_token: string; expires_at: string }>(`/v1/platform/tenants/${enc(id)}/recovery`, { ...platformRealm, method: "POST", json: { email, ...reasonBody(reason) } }),
  assignTenantPlan: (id: string, planId: string, acknowledge = false, reason?: string) => request<PlatformQuotaOverride & { plan_id: string; plan_code: string }>(`/v1/platform/tenants/${enc(id)}/plan`, { ...platformRealm, method: 'POST', json: { plan_id: planId, acknowledge_below_usage: acknowledge, ...reasonBody(reason) } }),
  status: (token?: string) =>
    request<PlatformStatus>("/v1/platform/status", {
      realm: token ? "public" : "platform",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    }),
  listTenants: () => request<{ items: PlatformTenant[] }>("/v1/platform/tenants", platformRealm),
  getTenant: (id: string) => request<PlatformTenant>(`/v1/platform/tenants/${enc(id)}`, platformRealm),
  /** UC-27: the reason is required and stored in the audit trail. */
  setTenantStatus: (id: string, status: PlatformTenantStatus, reason: string) =>
    request<PlatformTenant>(`/v1/platform/tenants/${enc(id)}/status`, {
      ...platformRealm,
      method: "POST",
      json: { status, reason: reason.trim() },
    }),
  setQuotaOverrides: (id: string, overrides: Record<string, unknown>, acknowledge = false, reason?: string) =>
    request<PlatformQuotaOverride>(`/v1/platform/tenants/${enc(id)}/quotas`, {
      ...platformRealm,
      method: "POST",
      json: { overrides, acknowledge_below_usage: acknowledge, ...reasonBody(reason) },
    }),
  listPlans: () => request<PlatformPlan[]>("/v1/platform/plans", platformRealm),
  updatePlan: (id: string, value: Pick<PlatformPlan, "name" | "limits" | "is_active">, acknowledge = false, reason?: string) =>
    request<PlatformPlan>(`/v1/platform/plans/${enc(id)}`, { ...platformRealm, method: "PUT", json: { ...value, acknowledge_below_usage: acknowledge, ...reasonBody(reason) } }),
  login: (email: string, password: string) =>
    request<OperatorSession>("/v1/platform/auth/login", { realm: "public", method: "POST", json: { email, password } }),
  me: (token?: string) =>
    request<PlatformMe>("/v1/platform/me", { realm: token ? "public" : "platform", headers: token ? { Authorization: `Bearer ${token}` } : undefined }),
  listOperators: () => request<{ items: PlatformOperator[] }>("/v1/platform/operators", platformRealm),
  createOperator: (input: { email: string; display_name: string; password: string; roles: PlatformOperator["roles"] }) =>
    request<PlatformOperator>("/v1/platform/operators", { ...platformRealm, method: "POST", json: input }),
  updateOperator: (id: string, change: Partial<{ display_name: string; roles: PlatformOperator["roles"]; status: PlatformOperator["status"]; password: string }>) =>
    request<PlatformOperator>(`/v1/platform/operators/${enc(id)}`, { ...platformRealm, method: "PATCH", json: change }),
  listFailures: () => request<{ items: PlatformFailure[] }>("/v1/platform/failures", platformRealm),
  /** UC-29: every tenant's usage against its limits. */
  listUsage: () => request<{ items: PlatformTenantUsage[] }>("/v1/platform/usage", platformRealm),
  /** UC-31: filtered, paginated audit history (newest first). */
  listAudit: (filters: { tenant_id?: string; action?: string; outcome?: string; before?: string; limit?: number } = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString();
    return request<{ items: PlatformAudit[]; next_before: string | null }>(`/v1/platform/audit${query ? `?${query}` : ""}`, platformRealm);
  },
};

/** UC-31: this tenant's own audit trail (administrators). */
export const tenantAudit = {
  list: (filters: { action?: string; outcome?: string; before?: string; limit?: number } = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString();
    return request<{ items: TenantAuditItem[]; next_before: string | null }>(`/v1/audit${query ? `?${query}` : ""}`);
  },
};
