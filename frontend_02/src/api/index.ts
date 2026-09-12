import { request } from "./client";
import type {
  ApiKeyCreateInput,
  ApiKeyResource,
  ApiKeyRotateInput,
  ApiKeySecretResource,
  AuthTokenPair,
  AutoscalingStatus,
  DatasetSnapshotResource,
  DatasetUploadResponse,
  DeploymentStatus,
  EventBatchResponse,
  EventSubmit,
  EventSubmitResponse,
  LoginInput,
  MetricsSummary,
  ModelVersionResource,
  PlatformAudit,
  PlatformFailure,
  PlatformPlan,
  PlatformQuotaOverride,
  PlatformStatus,
  PlatformTenant,
  PlatformTenantStatus,
  ProductBulkUpsertResponse,
  ProductListResponse,
  ProductResource,
  ProductUpsert,
  ReplicaStatusResponse,
  SetupPasswordInput,
  SubscriptionResult,
  TenantRegistrationInput,
  TenantRegistrationResult,
  TrainingJobCreate,
  TrainingJobResource,
  UsageSummaryResult,
} from "./types";

const enc = encodeURIComponent;

// ── public ─────────────────────────────────────────────────────
export const auth = {
  login: (input: LoginInput) =>
    request<AuthTokenPair>("/v1/auth/login", { method: "POST", json: input, realm: "public" }),
  setupPassword: (input: SetupPasswordInput) =>
    request<AuthTokenPair>("/v1/auth/setup-password", { method: "POST", json: input, realm: "public" }),
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
};

export const products = {
  list: () => request<ProductListResponse>("/v1/products"),
  get: (externalId: string) => request<ProductResource>(`/v1/products/${enc(externalId)}`),
  put: (externalId: string, input: ProductUpsert) =>
    request<ProductResource>(`/v1/products/${enc(externalId)}`, { method: "PUT", json: input }),
  disable: (externalId: string) =>
    request<ProductResource>(`/v1/products/${enc(externalId)}:disable`, { method: "POST" }),
  bulkUpsert: (items: ProductUpsert[]) =>
    request<ProductBulkUpsertResponse>("/v1/products:bulk-upsert", { method: "POST", json: { products: items } }),
};

export const events = {
  submit: (input: EventSubmit) => request<EventSubmitResponse>("/v1/events", { method: "POST", json: input }),
  submitBatch: (items: EventSubmit[]) =>
    request<EventBatchResponse>("/v1/events/batches", { method: "POST", json: { events: items } }),
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
  createSnapshot: (input: { cutoff_at?: string | null; description?: string | null }) =>
    request<DatasetSnapshotResource>("/v1/datasets/snapshots", { method: "POST", json: input }),
};

export const models = {
  list: () => request<{ items: ModelVersionResource[] }>("/v1/model-versions"),
  get: (id: string) => request<ModelVersionResource>(`/v1/model-versions/${enc(id)}`),
  activate: (id: string) =>
    request<ModelVersionResource>(`/v1/model-versions/${enc(id)}:activate`, { method: "POST" }),
  archive: (id: string) =>
    request<ModelVersionResource>(`/v1/model-versions/${enc(id)}:archive`, { method: "POST" }),
  rollback: (targetId: string) =>
    request<ModelVersionResource>(`/v1/models/${enc(targetId)}:rollback`, { method: "POST" }),
};

export const training = {
  list: () => request<{ items: TrainingJobResource[] }>("/v1/training-jobs"),
  create: (input: TrainingJobCreate) =>
    request<TrainingJobResource>("/v1/training-jobs", { method: "POST", json: input }),
};

export const serving = {
  deployment: () => request<DeploymentStatus>("/v1/deployment"),
  replicas: () => request<ReplicaStatusResponse>("/v1/deployment/replicas"),
  autoscaling: () => request<AutoscalingStatus>("/v1/deployment/autoscaling"),
  metrics: () => request<MetricsSummary>("/v1/metrics/summary"),
};

// ── platform ───────────────────────────────────────────────────
const platformRealm = { realm: "platform" as const };

export const platform = {
  status: (token?: string) =>
    request<PlatformStatus>("/v1/platform/status", {
      realm: token ? "public" : "platform",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    }),
  listTenants: () => request<{ items: PlatformTenant[] }>("/v1/platform/tenants", platformRealm),
  getTenant: (id: string) => request<PlatformTenant>(`/v1/platform/tenants/${enc(id)}`, platformRealm),
  setTenantStatus: (id: string, status: PlatformTenantStatus) =>
    request<PlatformTenant>(`/v1/platform/tenants/${enc(id)}/status`, {
      ...platformRealm,
      method: "POST",
      json: { status },
    }),
  setQuotaOverrides: (id: string, overrides: Record<string, unknown>) =>
    request<PlatformQuotaOverride>(`/v1/platform/tenants/${enc(id)}/quotas`, {
      ...platformRealm,
      method: "POST",
      json: { overrides },
    }),
  listPlans: () => request<PlatformPlan[]>("/v1/platform/plans", platformRealm),
  listFailures: () => request<{ items: PlatformFailure[] }>("/v1/platform/failures", platformRealm),
  listAudit: () => request<{ items: PlatformAudit[] }>("/v1/platform/audit", platformRealm),
};
