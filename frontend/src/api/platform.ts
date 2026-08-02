import { GraphRecApiError } from "./types";

export interface PlatformTenant {
  id: string;
  slug: string;
  name: string;
  status: string;
  created_at: string;
}

export interface PlatformPlan {
  id: string;
  code: string;
  name: string;
  limits: Record<string, unknown>;
  is_active: boolean;
}

export interface PlatformFailure {
  id: string;
  tenant_id: string | null;
  event_type: string;
  severity: string;
  sanitized_detail: Record<string, unknown>;
  occurred_at: string;
}

export interface PlatformAudit {
  id: string;
  tenant_id: string;
  actor_type: string;
  action_type: string;
  resource_type: string;
  outcome: string;
  occurred_at: string;
}

export async function listPlatformTenants(token: string): Promise<{ items: PlatformTenant[] }> {
  const res = await fetch("/v1/platform/tenants", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as { items: PlatformTenant[] };
}

export async function listPlatformPlans(token: string): Promise<PlatformPlan[]> {
  const res = await fetch("/v1/platform/plans", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as PlatformPlan[];
}

export async function listPlatformFailures(token: string): Promise<{ items: PlatformFailure[] }> {
  const res = await fetch("/v1/platform/failures", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as { items: PlatformFailure[] };
}

export async function listPlatformAuditLogs(token: string): Promise<{ items: PlatformAudit[] }> {
  const res = await fetch("/v1/platform/audit", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as { items: PlatformAudit[] };
}

export async function getPlatformStatus(): Promise<Record<string, unknown>> {
  const res = await fetch("/v1/platform/status");
  const body = await res.json();
  if (!res.ok) throw new GraphRecApiError(res.status, body);
  return body as Record<string, unknown>;
}
