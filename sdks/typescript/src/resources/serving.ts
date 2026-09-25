import type { DeploymentStatus, MetricsSummary } from "../types.js";
import { Resource } from "./base.js";

export class Deployment extends Resource {
  async get(): Promise<DeploymentStatus> {
    return this.client.request<DeploymentStatus>("deployment.get");
  }
}

export class Metrics extends Resource {
  /** Serving measurements over the API's default window (the last 60 minutes). */
  async summary(): Promise<MetricsSummary> {
    return this.client.request<MetricsSummary>("metrics.summary");
  }
}
