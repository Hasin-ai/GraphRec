import { InputValidationError } from "../errors.js";
import type { ApiKey, ApiKeyList, ApiKeyScope, ApiKeyWithSecret } from "../types.js";
import { Resource, toIso } from "./base.js";

export interface CreateApiKeyOptions {
  name: string;
  scopes: readonly ApiKeyScope[];
  /** Absolute expiry; omit for a key that does not expire. */
  expiresAt?: string | Date | null;
  /** Convenience: expire this many days from now. */
  expiresInDays?: number;
}

export interface RotateApiKeyOptions {
  reason: string;
  /** Seconds the previous secret keeps working (0..86400). Default one hour. */
  gracePeriodSeconds?: number;
}

/** API-key lifecycle. Bearer tokens only: an API key can never manage API keys. */
export class ApiKeys extends Resource {
  async list(): Promise<ApiKeyList> {
    return this.client.request<ApiKeyList>("api_keys.list");
  }

  async get(keyId: string): Promise<ApiKey> {
    return this.client.request<ApiKey>("api_keys.get", { params: { key_id: keyId } });
  }

  /** Create a key. The returned `secret` is shown once; store it immediately. */
  async create(options: CreateApiKeyOptions): Promise<ApiKeyWithSecret> {
    const name = options.name?.trim();
    if (!name || name.length > 100) throw new InputValidationError("name must be 1-100 characters");
    const scopes = Array.from(new Set(options.scopes));
    if (!scopes.length || scopes.length > 12) throw new InputValidationError("scopes must contain 1-12 unique scopes");
    let expires: string | null = toIso(options.expiresAt) ?? null;
    if (options.expiresInDays !== undefined) {
      if (options.expiresInDays <= 0) throw new InputValidationError("expiresInDays must be positive");
      expires = new Date(Date.now() + options.expiresInDays * 86_400_000).toISOString();
    }
    return this.client.request<ApiKeyWithSecret>("api_keys.create", { json: { name, scopes, expires_at: expires } });
  }

  /** Issue a new secret; the old one keeps working for the grace period. */
  async rotate(keyId: string, options: RotateApiKeyOptions): Promise<ApiKeyWithSecret> {
    const reason = options.reason?.trim();
    if (!reason || reason.length > 500) throw new InputValidationError("reason must be 1-500 characters");
    const grace = options.gracePeriodSeconds ?? 3600;
    if (!Number.isInteger(grace) || grace < 0 || grace > 86_400) throw new InputValidationError("gracePeriodSeconds must be 0..86400");
    return this.client.request<ApiKeyWithSecret>("api_keys.rotate", { params: { key_id: keyId }, json: { reason, grace_period_seconds: grace } });
  }

  async revoke(keyId: string): Promise<ApiKey> {
    return this.client.request<ApiKey>("api_keys.revoke", { params: { key_id: keyId } });
  }
}
