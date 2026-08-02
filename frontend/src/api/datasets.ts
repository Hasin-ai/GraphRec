import { GraphRecApiError } from "./types";

export interface DatasetSnapshotResource {
  id: string;
  tenant_id: string;
  training_job_id: string | null;
  cutoff_at: string;
  event_count: number;
  product_count: number;
  user_count: number;
  artifact_uri: string;
  checksum: string;
  created_at: string;
}

export interface DatasetSnapshotListResponse {
  items: DatasetSnapshotResource[];
}

export interface DatasetUploadResponse {
  accepted_events: number;
  accepted_products: number;
  dataset_snapshot: DatasetSnapshotResource;
}

async function parseResponseJson(res: Response): Promise<any> {
  try {
    return await res.json();
  } catch {
    return {
      code: "http_error",
      message: res.statusText || `Server returned HTTP status ${res.status}`,
    };
  }
}

export async function uploadDatasetFile(
  token: string,
  file: File,
): Promise<DatasetUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch("/v1/datasets/upload", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });

  const body = await parseResponseJson(res);
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as DatasetUploadResponse;
}

export async function createDatasetSnapshot(
  token: string,
  cutoffAt?: string,
): Promise<DatasetSnapshotResource> {
  const res = await fetch("/v1/datasets/snapshots", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ cutoff_at: cutoffAt || null }),
  });

  const body = await parseResponseJson(res);
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as DatasetSnapshotResource;
}

export async function listDatasetSnapshots(token: string): Promise<DatasetSnapshotListResponse> {
  const res = await fetch("/v1/datasets/snapshots", {
    headers: { Authorization: `Bearer ${token}` },
  });

  const body = await parseResponseJson(res);
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as DatasetSnapshotListResponse;
}
