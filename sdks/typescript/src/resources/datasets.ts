import { InputValidationError } from "../errors.js";
import type { DatasetSnapshot, DatasetSnapshotList, DatasetUploadResult } from "../types.js";
import { Resource, toIso } from "./base.js";

export type DatasetSource = Blob | string | Uint8Array;

export interface UploadOptions {
  /** File name sent in the multipart part (`dataset.json` / `dataset.csv`). */
  filename?: string;
  contentType?: string;
}

export class Datasets extends Resource {
  /**
   * Upload a JSON or CSV dataset of products and events in one step
   * (`POST /v1/datasets/upload`, multipart, 10 MiB). Needs both `catalog:write`
   * and `events:write`. The server upserts the catalog, submits the events and
   * returns the snapshot it took.
   */
  async upload(source: DatasetSource, options: UploadOptions = {}): Promise<DatasetUploadResult> {
    let blob: Blob;
    if (source instanceof Blob) blob = source;
    else if (typeof source === "string" || source instanceof Uint8Array) blob = new Blob([source], { type: options.contentType ?? guessType(source, options.filename) });
    else throw new InputValidationError("upload() takes a Blob/File, a string or a Uint8Array");
    if (blob.size === 0) throw new InputValidationError("The dataset is empty");
    const form = new FormData();
    form.append("file", blob, options.filename ?? (blob instanceof File ? blob.name : "dataset.json"));
    return this.client.request<DatasetUploadResult>("datasets.upload", { multipart: form });
  }

  /** Freeze the current products and events into an immutable snapshot a training job can build from. */
  async createSnapshot(options: { cutoffAt?: string | Date | null; description?: string | null } = {}): Promise<DatasetSnapshot> {
    return this.client.request<DatasetSnapshot>("datasets.create_snapshot", {
      json: { cutoff_at: toIso(options.cutoffAt) ?? null, description: options.description ?? null },
    });
  }

  async listSnapshots(): Promise<DatasetSnapshotList> {
    return this.client.request<DatasetSnapshotList>("datasets.list_snapshots");
  }

  async getSnapshot(snapshotId: string): Promise<DatasetSnapshot> {
    return this.client.request<DatasetSnapshot>("datasets.get_snapshot", { params: { snapshot_id: snapshotId } });
  }
}

function guessType(source: string | Uint8Array, filename?: string): string {
  if (filename?.toLowerCase().endsWith(".csv")) return "text/csv";
  if (filename?.toLowerCase().endsWith(".json")) return "application/json";
  const head = typeof source === "string" ? source.trimStart().slice(0, 1) : String.fromCharCode(source[0] ?? 0);
  return head === "{" || head === "[" ? "application/json" : "text/csv";
}
