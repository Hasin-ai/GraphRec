import {
  GraphRecApiError,
  type ModelVersionCreate,
  type ModelVersionListResponse,
  type ModelVersionResource,
  type TrainingJobCreate,
  type TrainingJobListResponse,
  type TrainingJobResource,
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

export async function registerModelVersion(
  token: string,
  payload: ModelVersionCreate,
): Promise<ModelVersionResource> {
  const response = await fetch("/v1/model-versions", {
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
  return body as ModelVersionResource;
}

export async function listModelVersions(token: string): Promise<ModelVersionListResponse> {
  const response = await fetch("/v1/model-versions", {
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
  return body as ModelVersionListResponse;
}

export async function activateModelVersion(
  token: string,
  versionId: string,
): Promise<ModelVersionResource> {
  const response = await fetch(`/v1/model-versions/${versionId}:activate`, {
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
  return body as ModelVersionResource;
}

export async function rollbackModel(token: string, modelId: string): Promise<ModelVersionResource> {
  const response = await fetch(`/v1/models/${modelId}:rollback`, {
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
  return body as ModelVersionResource;
}

export async function archiveModelVersion(
  token: string,
  versionId: string,
): Promise<ModelVersionResource> {
  const response = await fetch(`/v1/model-versions/${versionId}:archive`, {
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
  return body as ModelVersionResource;
}

export async function createTrainingJob(
  token: string,
  payload: TrainingJobCreate,
): Promise<TrainingJobResource> {
  const response = await fetch("/v1/training-jobs", {
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
  return body as TrainingJobResource;
}

export async function listTrainingJobs(token: string): Promise<TrainingJobListResponse> {
  const response = await fetch("/v1/training-jobs", {
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
  return body as TrainingJobListResponse;
}
