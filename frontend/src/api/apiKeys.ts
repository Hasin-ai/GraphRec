import {
  GraphRecApiError,
  type ApiKeyCreateInput,
  type ApiKeyListResult,
  type ApiKeyResource,
  type ApiKeyRotateInput,
  type ApiKeySecretResource,
} from "./types";

async function request<T>(
  path: string,
  accessToken: string,
  init: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  const body = (await response.json()) as T | { error?: object };
  if (!response.ok) {
    throw new GraphRecApiError(
      response.status,
      body as ConstructorParameters<typeof GraphRecApiError>[1],
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }
  return body as T;
}

export function listApiKeys(accessToken: string): Promise<ApiKeyListResult> {
  return request("/v1/api-keys", accessToken, { method: "GET" });
}

export function getApiKey(accessToken: string, keyId: string): Promise<ApiKeyResource> {
  return request(`/v1/api-keys/${encodeURIComponent(keyId)}`, accessToken, { method: "GET" });
}

export function createApiKey(
  accessToken: string,
  input: ApiKeyCreateInput,
): Promise<ApiKeySecretResource> {
  return request("/v1/api-keys", accessToken, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function rotateApiKey(
  accessToken: string,
  keyId: string,
  input: ApiKeyRotateInput,
): Promise<ApiKeySecretResource> {
  return request(`/v1/api-keys/${encodeURIComponent(keyId)}/rotate`, accessToken, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function revokeApiKey(accessToken: string, keyId: string): Promise<ApiKeyResource> {
  return request(`/v1/api-keys/${encodeURIComponent(keyId)}`, accessToken, { method: "DELETE" });
}
