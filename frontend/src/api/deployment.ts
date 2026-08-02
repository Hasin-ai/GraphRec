import { GraphRecApiError } from "./types";

export interface DeploymentStatus {
  status: string;
  active_model_version_id: string | null;
  desired_model_version_id: string | null;
  desired_replicas: number;
  current_replicas: number;
  ready_replicas: number;
  last_transition_at: string;
  failure_reason: string | null;
}

export interface ReplicaItem {
  id: string;
  model_version_id: string | null;
  status: string;
  ready: boolean;
  started_at: string;
}

export interface ReplicaStatusResponse {
  desired_replicas: number;
  current_replicas: number;
  ready_replicas: number;
  replicas: ReplicaItem[];
}

export interface AutoscalingStatus {
  min_replicas: number;
  max_replicas: number;
  cpu_target_percent: number;
  inflight_target: number | null;
  desired_replicas: number;
  ready_replicas: number;
  capacity_blocked: boolean;
  metrics_available: boolean;
  recent_actions: Record<string, unknown>[];
}

export interface MetricsSummary {
  window_start: string;
  window_end: string;
  request_rate: number;
  error_rate: number;
  fallback_rate: number;
  p95_latency_ms: number;
  active_model_version_id: string | null;
  desired_replicas: number;
  ready_replicas: number;
  quality: {
    hit_at_10: number;
    ndcg_at_10: number;
    retrieval_recall_at_k: number;
    catalog_coverage: number;
    intra_list_diversity: number;
    training_loss: number;
    validation_loss: number;
    recorded_at: string;
  } | null;
}

export async function getDeploymentStatus(token: string): Promise<DeploymentStatus> {
  const res = await fetch("/v1/deployment", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as DeploymentStatus;
}

export async function getReplicaStatus(token: string): Promise<ReplicaStatusResponse> {
  const res = await fetch("/v1/deployment/replicas", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as ReplicaStatusResponse;
}

export async function getAutoscalingStatus(token: string): Promise<AutoscalingStatus> {
  const res = await fetch("/v1/deployment/autoscaling", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as AutoscalingStatus;
}

export async function getMetricsSummary(token: string): Promise<MetricsSummary> {
  const res = await fetch("/v1/metrics/summary", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as MetricsSummary;
}
