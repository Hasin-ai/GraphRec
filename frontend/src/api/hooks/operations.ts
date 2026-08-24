/**
 * Credentials, users, usage, service status, audit and the onboarding checklist.
 *
 * The grouping is by page rather than by backend router, because that is how
 * they are read: `/service-status` composes four endpoints and `/integration`
 * composes two, and a file per router would scatter each page across four.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import { tenantApi } from '../client';
import type { S } from '../schema';

// -------------------------------------------------------------- onboarding

export type Onboarding = S['OnboardingResponse'];

export const onboardingQuery = {
  queryKey: ['onboarding'] as const,
  queryFn: () => tenantApi.get<Onboarding>('/v1/onboarding'),
};

// ------------------------------------------------------------- credentials

export type Credential = S['CredentialResponse'];
export type IssuedCredential = S['IssuedCredentialResponse'];
export type ScopeDescriptor = S['ScopeDescriptor'];

export const credentialsQuery = (state?: string) => ({
  queryKey: ['credentials', state ?? null] as const,
  queryFn: () =>
    tenantApi.get<S['CredentialListResponse']>(
      `/v1/api-keys${state ? `?state=${encodeURIComponent(state)}` : ''}`,
    ),
});

/**
 * The scope catalogue. Effectively immutable, so it is cached for the session.
 *
 * It is a generated vocabulary — the same `CredentialScope` enum
 * `tests/contract/test_enum_parity.py` pins — so refetching it would ask the
 * server to repeat a constant.
 */
export const scopesQuery = {
  queryKey: ['scopes'] as const,
  queryFn: () => tenantApi.get<S['ScopeListResponse']>('/v1/scopes'),
  staleTime: Infinity,
};

export function createCredential(
  body: S['CreateCredentialRequest'],
): Promise<IssuedCredential> {
  return tenantApi.post<IssuedCredential>('/v1/api-keys', body);
}

export function rotateCredential(
  keyId: string,
  body: S['RotateCredentialRequest'],
): Promise<IssuedCredential> {
  return tenantApi.post<IssuedCredential>(
    `/v1/api-keys/${encodeURIComponent(keyId)}:rotate`,
    body,
  );
}

export function revokeCredential(keyId: string): Promise<void> {
  return tenantApi.delete<void>(`/v1/api-keys/${encodeURIComponent(keyId)}`);
}

// ------------------------------------------------------------------- users

export type TenantUser = S['UserResponse'];
export type Invitation = S['InvitationResponse'];

export const usersQuery = {
  queryKey: ['users'] as const,
  queryFn: () => tenantApi.get<S['UserListResponse']>('/v1/users'),
};

export const userQuery = (userId: string) => ({
  queryKey: ['user', userId] as const,
  queryFn: () => tenantApi.get<TenantUser>(`/v1/users/${encodeURIComponent(userId)}`),
  retry: false,
});

export function inviteUser(body: S['CreateUserRequest']): Promise<Invitation> {
  return tenantApi.post<Invitation>('/v1/users', body);
}

export function resendInvitation(userId: string): Promise<Invitation> {
  return tenantApi.post<Invitation>(
    `/v1/users/${encodeURIComponent(userId)}:resend-invitation`,
  );
}

export function changeUserRole(
  userId: string,
  body: S['ChangeRoleRequest'],
): Promise<TenantUser> {
  return tenantApi.patch<TenantUser>(
    `/v1/users/${encodeURIComponent(userId)}/role`,
    body,
  );
}

export function changeUserStatus(
  userId: string,
  body: S['ChangeStatusRequest'],
): Promise<TenantUser> {
  return tenantApi.patch<TenantUser>(
    `/v1/users/${encodeURIComponent(userId)}/status`,
    body,
  );
}

// ----------------------------------------------------------------- account

export function updateOwnProfile(body: S['UpdateProfileRequest']): Promise<S['MeResponse']> {
  return tenantApi.patch<S['MeResponse']>('/v1/me', body);
}

export function changeOwnPassword(
  body: S['ChangeOwnPasswordRequest'],
): Promise<S['MeResponse']> {
  return tenantApi.post<S['MeResponse']>('/v1/me:change-password', body);
}

// ------------------------------------------------------------------- usage

export const usageQuery = {
  queryKey: ['usage'] as const,
  queryFn: () => tenantApi.get<S['UsageResponse']>('/v1/usage'),
};

export const usageTrendsQuery = (periods: number) => ({
  queryKey: ['usage-trends', periods] as const,
  queryFn: () =>
    tenantApi.get<S['UsageTrendsResponse']>(`/v1/usage/trends?periods=${periods}`),
});

export const subscriptionQuery = {
  queryKey: ['subscription'] as const,
  queryFn: () => tenantApi.get<S['SubscriptionResponse']>('/v1/subscription'),
};

// ---------------------------------------------------------- service status

/**
 * §10.8: 15 s, and never stopping. It is a live board.
 *
 * Four separate queries rather than one composed endpoint, because they have
 * genuinely different shapes and one of them (`/deployment/replicas`) is only
 * rendered when the reader expands the capacity section. Composing them
 * server-side would fetch the expensive one for every reader who does not.
 */
const LIVE = 15_000;

export const deploymentQuery = {
  queryKey: ['deployment'] as const,
  queryFn: () => tenantApi.get<S['DeploymentResponse']>('/v1/deployment'),
  refetchInterval: LIVE,
  retry: false,
};

export const replicasQuery = {
  queryKey: ['deployment-replicas'] as const,
  queryFn: () => tenantApi.get<S['DeploymentReplicasResponse']>('/v1/deployment/replicas'),
  refetchInterval: LIVE,
  retry: false,
};

export const metricsSummaryQuery = (windowHours: number) => ({
  queryKey: ['metrics-summary', windowHours] as const,
  queryFn: () =>
    tenantApi.get<S['MetricsSummaryResponse']>(
      `/v1/metrics/summary?window_hours=${windowHours}`,
    ),
  refetchInterval: LIVE,
  retry: false,
});

export const servingErrorsQuery = {
  queryKey: ['serving-errors'] as const,
  queryFn: () => tenantApi.get<S['ServingErrorsResponse']>('/v1/service-status/errors'),
  refetchInterval: LIVE,
  retry: false,
};

// ------------------------------------------------------------------- audit

export interface AuditFilters {
  action?: string;
  limit?: number;
  offset?: number;
}

export const auditQuery = (filters: AuditFilters) => ({
  queryKey: ['audit', filters] as const,
  queryFn: () => {
    const search = new URLSearchParams();
    if (filters.action) search.set('action', filters.action);
    search.set('limit', String(filters.limit ?? 25));
    search.set('offset', String(filters.offset ?? 0));
    return tenantApi.get<S['AuditLogListResponse']>(`/v1/audit-logs?${search.toString()}`);
  },
});

// ------------------------------------------------------------------ shared

export function useTenantQuery<T>(options: {
  queryKey: readonly unknown[];
  queryFn: () => Promise<T>;
}): UseQueryResult<T> {
  return useQuery(options);
}

/** Invalidates the user list and the checklist, which every user action moves. */
export function useUserMutation<TInput, TOutput>(action: (input: TInput) => Promise<TOutput>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      for (const key of [['users'], ['user'], ['onboarding'], ['me']]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
}

export function useCredentialMutation<TInput, TOutput>(
  action: (input: TInput) => Promise<TOutput>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['credentials'] });
      void client.invalidateQueries({ queryKey: ['onboarding'] });
    },
  });
}
