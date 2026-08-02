import {
  GraphRecApiError,
  type EventBatchResponse,
  type EventBatchSubmit,
  type EventSubmit,
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

export async function submitEvent(token: string, payload: EventSubmit): Promise<Record<string, unknown>> {
  const response = await fetch("/v1/events", {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
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
  return body as Record<string, unknown>;
}

export async function submitEventBatch(
  token: string,
  payload: EventBatchSubmit,
): Promise<EventBatchResponse> {
  const response = await fetch("/v1/events/batches", {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
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
  return body as EventBatchResponse;
}

export async function getEventBatch(token: string, batchId: string): Promise<EventBatchResponse> {
  const response = await fetch(`/v1/events/batches/${batchId}`, {
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
  return body as EventBatchResponse;
}
