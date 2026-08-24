/**
 * The platform realm's reads and writes.
 *
 * One file, unlike the tenant realm's four, because the platform console is
 * seven pages over one router and splitting it would be filing for its own
 * sake.
 *
 * Every mutation here invalidates on the `['platform']` prefix rather than on a
 * precise key. An operator who suspends a tenant changes the estate list, that
 * tenant's detail, the status board's `active_tenants` and — because the
 * suspension is audited — the audit log. Enumerating those is a list that goes
 * stale the first time a handler learns to touch something else; the coarse
 * invalidation costs a few refetches on a page an operator visits deliberately.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { platformApi } from '../client';
import type { S } from '../schema';

export type TenantRow = S['PlatformTenantRow'];
export type TenantDetail = S['PlatformTenantDetailResponse'];
export type PlanBody = S['PlanBody'];
export type PlanDetail = S['PlanDetailResponse'];
export type UsageRow = S['PlatformUsageRowBody'];
export type PlatformStatus = S['PlatformStatusResponse'];
export type FailureRow = S['FailureRowBody'];
export type AuditRow = S['PlatformAuditLogRow'];
export type QuotaOverride = S['QuotaOverrideBody'];

// ------------------------------------------------------------------ estate

export const tenantsQuery = (params: { status?: string; q?: string; offset?: number }) => {
  const search = new URLSearchParams();
  if (params.status) search.set('status', params.status);
  if (params.q) search.set('q', params.q);
  if (params.offset) search.set('offset', String(params.offset));
  const suffix = search.toString();
  return {
    queryKey: ['platform', 'tenants', params.status ?? null, params.q ?? '', params.offset ?? 0],
    queryFn: () =>
      platformApi.get<S['PlatformTenantListResponse']>(
        `/v1/platform/tenants${suffix ? `?${suffix}` : ''}`,
      ),
  };
};

export const tenantDetailQuery = (tenantId: string) => ({
  queryKey: ['platform', 'tenants', tenantId] as const,
  queryFn: () => platformApi.get<TenantDetail>(`/v1/platform/tenants/${tenantId}`),
});

// ------------------------------------------------------------------- plans

export const plansQuery = {
  queryKey: ['platform', 'plans'] as const,
  queryFn: () => platformApi.get<S['PlanListResponse']>('/v1/platform/plans'),
};

export const planDetailQuery = (planId: string) => ({
  queryKey: ['platform', 'plans', planId] as const,
  queryFn: () => platformApi.get<PlanDetail>(`/v1/platform/plans/${planId}`),
});

// ------------------------------------------------------------------- usage

export const platformUsageQuery = (params: { period?: string; usage_type?: string }) => {
  const search = new URLSearchParams();
  if (params.period) search.set('period', params.period);
  if (params.usage_type) search.set('usage_type', params.usage_type);
  const suffix = search.toString();
  return {
    queryKey: ['platform', 'usage', params.period ?? null, params.usage_type ?? null],
    queryFn: () =>
      platformApi.get<S['PlatformUsageListResponse']>(
        `/v1/platform/usage${suffix ? `?${suffix}` : ''}`,
      ),
  };
};

// ------------------------------------------------------------------ status

/** 15 s, and it never stops: §10.8 calls this a live board. */
export const platformStatusQuery = {
  queryKey: ['platform', 'status'] as const,
  queryFn: () => platformApi.get<PlatformStatus>('/v1/platform/status'),
  refetchInterval: 15_000,
};

// ------------------------------------------------------ failures and audit

export const failuresQuery = (params: { area?: string; severity?: string }) => {
  const search = new URLSearchParams();
  if (params.area) search.set('area', params.area);
  if (params.severity) search.set('severity', params.severity);
  const suffix = search.toString();
  return {
    queryKey: ['platform', 'failures', params.area ?? null, params.severity ?? null],
    queryFn: () =>
      platformApi.get<S['FailureListResponse']>(
        `/v1/platform/failures${suffix ? `?${suffix}` : ''}`,
      ),
  };
};

export const platformAuditQuery = (params: {
  action?: string;
  outcome?: string;
  offset?: number;
}) => {
  const search = new URLSearchParams();
  if (params.action) search.set('action', params.action);
  if (params.outcome) search.set('outcome', params.outcome);
  if (params.offset) search.set('offset', String(params.offset));
  const suffix = search.toString();
  return {
    queryKey: [
      'platform',
      'audit',
      params.action ?? null,
      params.outcome ?? null,
      params.offset ?? 0,
    ],
    queryFn: () =>
      platformApi.get<S['PlatformAuditListResponse']>(
        `/v1/platform/audit-logs${suffix ? `?${suffix}` : ''}`,
      ),
  };
};

// --------------------------------------------------------------- mutations

export function changeTenantStatus(tenantId: string, body: S['ChangeTenantStatusRequest']) {
  return platformApi.post<TenantRow>(`/v1/platform/tenants/${tenantId}:change-status`, body);
}

export function assignPlan(tenantId: string, body: S['AssignPlanRequest']) {
  return platformApi.post<TenantRow>(`/v1/platform/tenants/${tenantId}/plan`, body);
}

export function grantOverride(tenantId: string, body: S['GrantOverrideRequest']) {
  return platformApi.post<QuotaOverride>(
    `/v1/platform/tenants/${tenantId}/quota-overrides`,
    body,
  );
}

export function updatePlan(planId: string, body: S['UpdatePlanRequest']) {
  return platformApi.patch<PlanBody>(`/v1/platform/plans/${planId}`, body);
}

export function createPlan(body: S['CreatePlanRequest']) {
  return platformApi.post<PlanBody>('/v1/platform/plans', body);
}

export function closePlan(planId: string) {
  return platformApi.post<PlanBody>(`/v1/platform/plans/${planId}:close`, undefined);
}

/**
 * Every platform write goes through this.
 *
 * The invalidation is deliberately coarse — see the module docstring. The
 * alternative is a per-mutation key list that is correct on the day it is
 * written and wrong by the next handler.
 */
export function usePlatformMutation<Body, Result>(
  action: (body: Body) => Promise<Result>,
): ReturnType<typeof useMutation<Result, Error, Body>> {
  const queryClient = useQueryClient();
  return useMutation<Result, Error, Body>({
    mutationFn: action,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['platform'] });
    },
  });
}
