/**
 * Who the caller is, in each of the two realms.
 *
 * These three queries back every guard in the console, so they are cached
 * aggressively and shared: a route tree where `TenantLayout`, the sidebar and
 * a page all ask "what is my role" must ask the server once.
 *
 * `retry: false` throughout. A 401 or 403 from an identity query is an answer,
 * not a failure — retrying it three times delays the redirect the guard is
 * about to perform and puts three refusals in the audit log where one belongs.
 */

import { useQuery } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import { platformApi, tenantApi } from '../client';
import type { PlatformPermission, TenantRole } from '../../lib/enums';

export interface Me {
  tenant_user_id: string;
  tenant_id: string;
  email: string;
  display_name: string;
  role: TenantRole;
  status: string;
}

export interface TenantSummary {
  tenant_id: string;
  tenant_code: string;
  tenant_name: string;
  status: string;
  plan_code: string | null;
  created_at: string;
  status_reason: string | null;
}

export interface PlatformMe {
  platform_user_id: string;
  email: string;
  display_name: string;
  // Typed as the generated enum rather than `string[]`: the vocabulary is
  // pinned on both sides by `tests/contract/test_enum_parity.py`, so a value
  // outside it is a contract break rather than a case to handle.
  permissions: PlatformPermission[];
}

export const meQuery = {
  queryKey: ['me'] as const,
  queryFn: () => tenantApi.get<Me>('/v1/me'),
  retry: false,
  staleTime: 5 * 60 * 1000,
};

export const tenantQuery = {
  queryKey: ['tenant'] as const,
  // The one read gate 2 exempts, so `/account/tenant-status` can render. See
  // `current_tenant_principal_any_state` in the backend for why.
  queryFn: () => tenantApi.get<TenantSummary>('/v1/tenant'),
  retry: false,
  staleTime: 60 * 1000,
};

export const platformMeQuery = {
  queryKey: ['platform', 'me'] as const,
  queryFn: () => platformApi.get<PlatformMe>('/v1/platform/me'),
  retry: false,
  staleTime: 5 * 60 * 1000,
};

export function useMe(): UseQueryResult<Me> {
  return useQuery(meQuery);
}

export function useTenant(): UseQueryResult<TenantSummary> {
  return useQuery(tenantQuery);
}

export function usePlatformMe(): UseQueryResult<PlatformMe> {
  return useQuery(platformMeQuery);
}
