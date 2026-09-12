import type { AutoscalingStatus, DeploymentStatus, MetricsSummary, ReplicaStatus } from "../types.js";
import { Resource } from "./base.js";

export class Deployment extends Resource {
  async get(): Promise<DeploymentStatus> {
    return this.client.request<DeploymentStatus>("deployment.get");
  }
  async replicas(): Promise<ReplicaStatus> {
    return this.client.request<ReplicaStatus>("deployment.replicas");
  }
  async autoscaling(): Promise<AutoscalingStatus> {
    return this.client.request<AutoscalingStatus>("deployment.autoscaling");
  }
}

export class Metrics extends Resource {
  async summary(): Promise<MetricsSummary> {
    return this.client.request<MetricsSummary>("metrics.summary");
  }
}
