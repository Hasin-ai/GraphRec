/**
 * Single source of truth for every GraphRec HTTP route the SDK calls.
 *
 * Each resource method looks up its route here, and `tests/contract.test.ts`
 * compares this table with the FastAPI routers in `apps/api/routes` (and with
 * the Python SDK's table) so the SDKs and the server cannot silently drift.
 */

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
/**
 * `none` - never send credentials; `any` - an API key or bearer token is
 * required; `bearer` - a user token (or the platform token) is required.
 */
export type AuthMode = "none" | "any" | "bearer";
export type BodyKind = "none" | "json" | "multipart";

export interface Route {
  readonly key: string;
  readonly method: HttpMethod;
  readonly path: string;
  readonly auth: AuthMode;
  readonly scope?: string;
  /** Scopes required in addition to `scope`. */
  readonly extraScopes: readonly string[];
  /** Safe to retry after an ambiguous failure (timeout, dropped connection). */
  readonly idempotent: boolean;
  readonly body: BodyKind;
}

const PARAM = /\{([a-z_]+)\}/g;

interface RouteSpec {
  auth?: AuthMode;
  scope?: string;
  extraScopes?: readonly string[];
  idempotent?: boolean;
  body?: BodyKind;
}

function r(key: string, method: HttpMethod, path: string, spec: RouteSpec = {}): [string, Route] {
  return [
    key,
    {
      key,
      method,
      path,
      auth: spec.auth ?? "any",
      scope: spec.scope,
      extraScopes: spec.extraScopes ?? [],
      idempotent: spec.idempotent ?? false,
      body: spec.body ?? "none",
    },
  ];
}

// prettier-ignore
export const ROUTES: ReadonlyMap<string, Route> = new Map<string, Route>([
  // -- health --------------------------------------------------------------------------
  r("health.check", "GET", "/healthz", { auth: "none", idempotent: true }),
  // -- tenants & authentication --------------------------------------------------------
  r("tenants.register", "POST", "/v1/tenants", { auth: "none", idempotent: true, body: "json" }),
  r("auth.login", "POST", "/v1/auth/login", { auth: "none", idempotent: true, body: "json" }),
  r("auth.setup_password", "POST", "/v1/auth/setup-password", { auth: "none", idempotent: true, body: "json" }),
  // -- API keys (bearer tokens only) ---------------------------------------------------
  r("api_keys.list", "GET", "/v1/api-keys", { auth: "bearer", scope: "keys:write", idempotent: true }),
  r("api_keys.get", "GET", "/v1/api-keys/{key_id}", { auth: "bearer", scope: "keys:write", idempotent: true }),
  r("api_keys.create", "POST", "/v1/api-keys", { auth: "bearer", scope: "keys:write", body: "json" }),
  r("api_keys.rotate", "POST", "/v1/api-keys/{key_id}/rotate", { auth: "bearer", scope: "keys:write", body: "json" }),
  r("api_keys.revoke", "DELETE", "/v1/api-keys/{key_id}", { auth: "bearer", scope: "keys:write", idempotent: true }),
  // -- billing -------------------------------------------------------------------------
  r("subscription.get", "GET", "/v1/subscription", { scope: "billing:read", idempotent: true }),
  r("usage.get", "GET", "/v1/usage", { scope: "usage:read", idempotent: true }),
  // -- catalog -------------------------------------------------------------------------
  r("products.bulk_upsert", "POST", "/v1/products:bulk-upsert", { scope: "catalog:write", idempotent: true, body: "json" }),
  r("products.list", "GET", "/v1/products", { scope: "catalog:read", idempotent: true }),
  r("products.get", "GET", "/v1/products/{external_id}", { scope: "catalog:read", idempotent: true }),
  r("products.upsert", "PUT", "/v1/products/{external_id}", { scope: "catalog:write", idempotent: true, body: "json" }),
  r("products.update", "PATCH", "/v1/products/{external_id}", { scope: "catalog:write", idempotent: true, body: "json" }),
  r("products.disable", "POST", "/v1/products/{external_id}:disable", { scope: "catalog:write", idempotent: true }),
  // -- customer events -----------------------------------------------------------------
  r("events.create", "POST", "/v1/events", { scope: "events:write", idempotent: true, body: "json" }),
  r("events.create_batch", "POST", "/v1/events/batches", { scope: "events:write", idempotent: true, body: "json" }),
  r("events.list_batches", "GET", "/v1/events/batches", { scope: "events:read", idempotent: true }),
  r("events.get_batch", "GET", "/v1/events/batches/{batch_id}", { scope: "events:read", idempotent: true }),
  // -- datasets ------------------------------------------------------------------------
  r("datasets.upload", "POST", "/v1/datasets/upload", { scope: "catalog:write", extraScopes: ["events:write"], body: "multipart" }),
  r("datasets.create_snapshot", "POST", "/v1/datasets/snapshots", { scope: "training:write", body: "json" }),
  r("datasets.list_snapshots", "GET", "/v1/datasets/snapshots", { scope: "training:read", idempotent: true }),
  r("datasets.get_snapshot", "GET", "/v1/datasets/snapshots/{snapshot_id}", { scope: "training:read", idempotent: true }),
  // -- model registry & training -------------------------------------------------------
  r("model_versions.create", "POST", "/v1/model-versions", { scope: "models:write", body: "json" }),
  r("model_versions.list", "GET", "/v1/model-versions", { scope: "models:read", idempotent: true }),
  r("model_versions.get", "GET", "/v1/model-versions/{version_id}", { scope: "models:read", idempotent: true }),
  r("model_versions.activate", "POST", "/v1/model-versions/{version_id}:activate", { scope: "models:deploy", idempotent: true }),
  r("model_versions.archive", "POST", "/v1/model-versions/{version_id}:archive", { scope: "models:write", idempotent: true }),
  r("model_versions.rollback", "POST", "/v1/models/{model_id}:rollback", { scope: "models:deploy", idempotent: true }),
  r("training_jobs.create", "POST", "/v1/training-jobs", { scope: "training:write", body: "json" }),
  r("training_jobs.list", "GET", "/v1/training-jobs", { scope: "training:read", idempotent: true }),
  // -- serving status ------------------------------------------------------------------
  r("deployment.get", "GET", "/v1/deployment", { scope: "deployments:read", idempotent: true }),
  r("deployment.replicas", "GET", "/v1/deployment/replicas", { scope: "deployments:read", idempotent: true }),
  r("deployment.autoscaling", "GET", "/v1/deployment/autoscaling", { scope: "deployments:read", idempotent: true }),
  r("metrics.summary", "GET", "/v1/metrics/summary", { scope: "metrics:read", idempotent: true }),
  // -- recommendations & feedback ------------------------------------------------------
  r("recommendations.get", "POST", "/v1/recommendations", { scope: "recommendations:read", idempotent: true, body: "json" }),
  r("recommendations.for_session", "POST", "/v1/recommendations/session", { scope: "recommendations:read", idempotent: true, body: "json" }),
  r("feedback.impression", "POST", "/v1/feedback/impressions", { scope: "events:write", idempotent: true, body: "json" }),
  r("feedback.click", "POST", "/v1/feedback/clicks", { scope: "events:write", idempotent: true, body: "json" }),
  r("feedback.conversion", "POST", "/v1/feedback/conversions", { scope: "events:write", idempotent: true, body: "json" }),
  // -- platform administration (PLATFORM_ADMIN_TOKEN bearer) ---------------------------
  r("platform.list_tenants", "GET", "/v1/platform/tenants", { auth: "bearer", scope: "platform:admin", idempotent: true }),
  r("platform.get_tenant", "GET", "/v1/platform/tenants/{tenant_id}", { auth: "bearer", scope: "platform:admin", idempotent: true }),
  r("platform.set_tenant_status", "POST", "/v1/platform/tenants/{tenant_id}/status", { auth: "bearer", scope: "platform:admin", idempotent: true, body: "json" }),
  r("platform.list_plans", "GET", "/v1/platform/plans", { auth: "bearer", scope: "platform:admin", idempotent: true }),
  r("platform.set_quota_override", "POST", "/v1/platform/tenants/{tenant_id}/quotas", { auth: "bearer", scope: "platform:admin", idempotent: true, body: "json" }),
  r("platform.list_failures", "GET", "/v1/platform/failures", { auth: "bearer", scope: "platform:admin", idempotent: true }),
  r("platform.list_audit_logs", "GET", "/v1/platform/audit", { auth: "bearer", scope: "platform:admin", idempotent: true }),
  r("platform.status", "GET", "/v1/platform/status", { auth: "bearer", scope: "platform:admin", idempotent: true }),
]);

export function route(key: string): Route {
  const found = ROUTES.get(key);
  if (!found) throw new Error(`Unknown GraphRec route '${key}'`);
  return found;
}

export function requiredScopes(r: Route): string[] {
  return r.scope ? [r.scope, ...r.extraScopes] : [...r.extraScopes];
}

export function routeParams(r: Route): string[] {
  return Array.from(r.path.matchAll(PARAM), (m) => m[1]);
}

export function buildPath(r: Route, params: Record<string, string | number> = {}): string {
  const missing = routeParams(r).filter((name) => !(name in params));
  if (missing.length) throw new Error(`Missing path parameter(s) for ${r.key}: ${missing.join(", ")}`);
  return r.path.replace(PARAM, (_, name: string) => {
    const raw = String(params[name]);
    if (raw === "") throw new Error(`Path parameter '${name}' must not be empty`);
    return encodeURIComponent(raw);
  });
}

/** `true` when the route is the platform realm (shared PLATFORM_ADMIN_TOKEN). */
export function isPlatformRoute(r: Route): boolean {
  return r.scope === "platform:admin";
}
