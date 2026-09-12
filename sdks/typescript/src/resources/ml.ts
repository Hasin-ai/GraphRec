import { InputValidationError, WaitTimeoutError } from "../errors.js";
import { sleep } from "../retry.js";
import type { ModelVersion, ModelVersionInput, ModelVersionList, TrainingJob, TrainingJobInput, TrainingJobList } from "../types.js";
import { Resource, compact } from "./base.js";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export class ModelVersions extends Resource {
  /** Register a version produced outside GraphRec (`POST /v1/model-versions`). */
  async create(input: ModelVersionInput): Promise<ModelVersion> {
    if (!input.version_tag?.trim() || input.version_tag.length > 64) throw new InputValidationError("version_tag must be 1-64 characters");
    if (!input.model_type?.trim() || input.model_type.length > 64) throw new InputValidationError("model_type must be 1-64 characters");
    return this.client.request<ModelVersion>("model_versions.create", { json: compact({ ...input, version_tag: input.version_tag.trim(), model_type: input.model_type.trim() }) });
  }

  async list(): Promise<ModelVersionList> {
    return this.client.request<ModelVersionList>("model_versions.list");
  }

  async get(versionId: string): Promise<ModelVersion> {
    return this.client.request<ModelVersion>("model_versions.get", { params: { version_id: versionId } });
  }

  /** The version currently serving traffic, or `null`. */
  async getActive(): Promise<ModelVersion | null> {
    const { items } = await this.list();
    return items.find((v) => v.status === "active") ?? null;
  }

  /** Make `versionId` serve all traffic; the previous active version is retired. */
  async activate(versionId: string): Promise<ModelVersion> {
    return this.client.request<ModelVersion>("model_versions.activate", { params: { version_id: versionId } });
  }

  /** Retain for audit only; the active version is rejected with `StateConflictError`. */
  async archive(versionId: string): Promise<ModelVersion> {
    return this.client.request<ModelVersion>("model_versions.archive", { params: { version_id: versionId } });
  }

  /** Re-activate a retired version (`POST /v1/models/{id}:rollback`). */
  async rollback(versionId: string): Promise<ModelVersion> {
    return this.client.request<ModelVersion>("model_versions.rollback", { params: { model_id: versionId } });
  }
}

export interface WaitOptions {
  timeoutMs?: number;
  pollIntervalMs?: number;
}

export class TrainingJobs extends Resource {
  /**
   * Request training (`POST /v1/training-jobs`). In this release the job runs
   * synchronously and returns as `succeeded` with its `model_version_id`.
   */
  async create(input: TrainingJobInput = {}): Promise<TrainingJob> {
    return this.client.request<TrainingJob>("training_jobs.create", {
      json: compact({ model_type: input.model_type ?? "simplified_dgsr", dataset_snapshot_id: input.dataset_snapshot_id ?? null, configuration: input.configuration }),
    });
  }

  async list(): Promise<TrainingJobList> {
    return this.client.request<TrainingJobList>("training_jobs.list");
  }

  /** The API has no single-job read; find it in the tenant's list. */
  async find(jobId: string): Promise<TrainingJob | null> {
    const { items } = await this.list();
    return items.find((j) => j.id === jobId) ?? null;
  }

  /** Poll until the job reaches a terminal state. */
  async wait(jobId: string, options: WaitOptions = {}): Promise<TrainingJob> {
    const timeoutMs = options.timeoutMs ?? 600_000;
    const interval = options.pollIntervalMs ?? 2_000;
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const job = await this.find(jobId);
      if (!job) throw new WaitTimeoutError(`Training job ${jobId} is not visible to this credential`);
      if (TERMINAL.has(job.status)) return job;
      if (Date.now() + interval > deadline) throw new WaitTimeoutError(`Training job ${jobId} did not finish within ${timeoutMs} ms (status ${job.status})`);
      await sleep(interval);
    }
  }
}
