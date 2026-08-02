import {
  GraphRecApiError,
  type ProductBulkUpsertRequest,
  type ProductBulkUpsertResponse,
  type ProductListResponse,
  type ProductResource,
} from "./types";

async function parseJsonResponse(response: Response): Promise<any> {
  try {
    return await response.json();
  } catch {
    return {
      code: "http_error",
      message: response.statusText || `Server returned HTTP status ${response.status}`,
    };
  }
}

export async function bulkUpsertProducts(
  token: string,
  payload: ProductBulkUpsertRequest,
  idempotencyKey: string,
): Promise<ProductBulkUpsertResponse> {
  const response = await fetch("/v1/products:bulk-upsert", {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(payload),
  });
  const body = await parseJsonResponse(response);
  if (!response.ok) {
    throw new GraphRecApiError(
      response.status,
      body,
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }
  return body as ProductBulkUpsertResponse;
}

export async function listProducts(token: string): Promise<ProductListResponse> {
  const response = await fetch("/v1/products", {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  const body = await parseJsonResponse(response);
  if (!response.ok) {
    throw new GraphRecApiError(
      response.status,
      body,
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }
  return body as ProductListResponse;
}

export async function disableProduct(token: string, externalId: string): Promise<ProductResource> {
  const response = await fetch(`/v1/products/${encodeURIComponent(externalId)}:disable`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  const body = await parseJsonResponse(response);
  if (!response.ok) {
    throw new GraphRecApiError(
      response.status,
      body,
      response.headers.get("X-Correlation-ID") ?? undefined,
    );
  }
  return body as ProductResource;
}
