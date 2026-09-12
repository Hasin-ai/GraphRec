import type { ApiKeyScope, TenantUserRole } from "../api/types";

/** The 14 API-key-compatible scopes (graphrec_core/api_keys/scopes.py), with console wording. */
export const API_KEY_SCOPES: { scope: ApiKeyScope; label: string; group: string }[] = [
  { scope: "catalog:read", label: "Catalog read", group: "Catalog" },
  { scope: "catalog:write", label: "Catalog write & synchronization", group: "Catalog" },
  { scope: "events:read", label: "Submission result read", group: "Events" },
  { scope: "events:write", label: "Event submission (single and batch) and feedback", group: "Events" },
  { scope: "recommendations:read", label: "Recommendation requests", group: "Serving" },
  { scope: "training:read", label: "Training and snapshot read", group: "Training" },
  { scope: "training:write", label: "Training request", group: "Training" },
  { scope: "models:read", label: "Model version read", group: "Models" },
  { scope: "models:write", label: "Model version registration and archive", group: "Models" },
  { scope: "models:deploy", label: "Model activation and roll back", group: "Models" },
  { scope: "deployments:read", label: "Deployment status read", group: "Serving" },
  { scope: "metrics:read", label: "Metrics summary read", group: "Serving" },
  { scope: "billing:read", label: "Subscription read", group: "Account" },
  { scope: "usage:read", label: "Usage read", group: "Account" },
];

const DEVELOPER_DELEGATED: ApiKeyScope[] = ["catalog:read", "catalog:write", "events:read", "events:write"];

/** Scopes a role may delegate to an API key (ADMIN_DELEGATED_SCOPES / DEVELOPER_DELEGATED_SCOPES). */
export function delegatableScopes(role: TenantUserRole): ApiKeyScope[] {
  return role === "tenant_administrator"
    ? API_KEY_SCOPES.map((s) => s.scope)
    : DEVELOPER_DELEGATED;
}

export function scopeLabel(scope: string): string {
  return API_KEY_SCOPES.find((s) => s.scope === scope)?.label ?? scope;
}

export const SCOPE_SHORT: Record<string, string> = {
  "catalog:read": "catalog read",
  "catalog:write": "catalog write",
  "events:read": "result read",
  "events:write": "event submission",
  "recommendations:read": "recommendations",
  "training:read": "training read",
  "training:write": "training request",
  "models:read": "models read",
  "models:write": "models write",
  "models:deploy": "activation",
  "deployments:read": "deployment read",
  "metrics:read": "metrics read",
  "billing:read": "subscription",
  "usage:read": "usage",
};
