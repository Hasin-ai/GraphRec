/**
 * Permission scopes.
 *
 * Tenant users receive scopes from their role; API keys receive the scopes
 * chosen when the key is created, limited to what the creating user may
 * delegate (`graphrec_core/api_keys/scopes.py`, `graphrec_core/auth/service.py`).
 */
import type { ApiKeyScope, Scope, TenantUserRole } from "./types.js";

/** Every scope an API key may carry (`keys:write` is bearer-token only). */
export const API_KEY_SCOPES: readonly ApiKeyScope[] = [
  "billing:read",
  "usage:read",
  "catalog:read",
  "catalog:write",
  "events:read",
  "events:write",
  "training:read",
  "training:write",
  "models:read",
  "models:write",
  "models:deploy",
  "recommendations:read",
  "deployments:read",
  "metrics:read",
];

/**
 * Scopes a console user's access token carries. Tokens keep the scopes granted
 * at login, so sign in again after the server changes them.
 */
export const ROLE_SCOPES: Readonly<Record<TenantUserRole, readonly Scope[]>> = {
  tenant_administrator: ["keys:write", ...API_KEY_SCOPES],
  tenant_developer: ["keys:write", "catalog:read", "catalog:write", "events:read", "events:write", "training:read"],
};

/** Scopes each role may grant to the API keys it creates. */
export const DELEGATABLE_SCOPES: Readonly<Record<TenantUserRole, readonly ApiKeyScope[]>> = {
  tenant_administrator: API_KEY_SCOPES,
  tenant_developer: ["catalog:read", "catalog:write", "events:read", "events:write"],
};

/**
 * A storefront backend: sync catalog, send events/feedback, fetch recommendations.
 * `recommendations:read` can only be delegated by a tenant administrator.
 */
export const STOREFRONT_KEY_SCOPES: readonly ApiKeyScope[] = ["catalog:read", "catalog:write", "events:read", "events:write", "recommendations:read"];

/** A catalog export job (PIM/ERP -> GraphRec). */
export const CATALOG_SYNC_KEY_SCOPES: readonly ApiKeyScope[] = ["catalog:read", "catalog:write"];
