/**
 * The six anonymous exchanges, plus sign-out.
 *
 * These are the only calls the console makes without a session, and they are
 * kept together because they share one property that the rest of the API does
 * not have: **the response is not allowed to be informative**. Sign-in,
 * recovery, invitation acceptance and registration all answer a stranger, so
 * none of them may confirm whether an account, a tenant or a token exists. The
 * server already refuses to disclose that; the job here is to not undo it by
 * rendering something more helpful than what came back.
 */

import { anonymous, request } from '../client';
import { clearSession, readRefreshToken, store } from '../session';
import type { SessionResponse, StoredSession } from '../session';

export interface RegisterTenantRequest {
  tenant_name: string;
  tenant_code: string;
  email: string;
  password: string;
}

export interface TenantResponse {
  tenant_id: string;
  tenant_code: string;
  tenant_name: string;
  status: string;
  plan_code: string | null;
  status_reason: string | null;
  created_at: string;
}

export interface SignInRequest {
  tenant_code: string;
  email: string;
  password: string;
}

export interface PlatformSignInRequest {
  email: string;
  password: string;
}

export interface RecoveryRequest {
  tenant_code: string;
  email: string;
}

export interface SetPasswordRequest {
  token: string;
  password: string;
  password_confirmation: string;
}

export interface UserResponse {
  tenant_user_id: string;
  email: string;
  display_name: string;
  role: string;
  status: string;
  created_at: string;
  last_authenticated_at: string | null;
}

/**
 * Registration creates the tenant and its first administrator, and returns the
 * tenant — **not** a session. The registrant signs in afterwards like anybody
 * else, which is why `/register` routes to `/login` rather than to `/home`.
 */
export function registerTenant(body: RegisterTenantRequest): Promise<TenantResponse> {
  return anonymous<TenantResponse>('/v1/tenants', body);
}

export async function signIn(body: SignInRequest): Promise<StoredSession> {
  const session = await anonymous<SessionResponse>('/v1/auth/sign-in', body);
  return store('tenant', session);
}

export async function platformSignIn(body: PlatformSignInRequest): Promise<StoredSession> {
  const session = await request<SessionResponse>('platform', '/v1/platform/auth/sign-in', {
    method: 'POST',
    body,
    authenticated: false,
  });
  return store('platform', session);
}

/** Step 1. Answers the same way whether or not the account exists. */
export function requestRecovery(body: RecoveryRequest): Promise<{ detail: string }> {
  return anonymous<{ detail: string }>('/v1/auth/recovery', body);
}

/** Step 2. Consumes the proof, revokes the account's other sessions. */
export function confirmRecovery(body: SetPasswordRequest): Promise<UserResponse> {
  return anonymous<UserResponse>('/v1/auth/recovery:confirm', body);
}

/** `invited → active`. The same shape as recovery, deliberately. */
export function acceptInvitation(body: SetPasswordRequest): Promise<UserResponse> {
  return anonymous<UserResponse>('/v1/invitations:accept', body);
}

/**
 * Sign out. The local half is unconditional.
 *
 * Revoking server-side is the part that matters and the part that can fail, so
 * the failure is swallowed: a caller who has decided to leave must not be kept
 * signed in by a network error. The refresh token is discarded either way, and
 * an unrevoked token the console has forgotten expires on its own.
 */
export async function signOut(): Promise<void> {
  const refreshToken = readRefreshToken('tenant');
  try {
    if (refreshToken) {
      await request<void>('tenant', '/v1/auth/sign-out', {
        method: 'POST',
        body: { refresh_token: refreshToken },
      });
    }
  } catch {
    // Deliberately ignored — see above.
  } finally {
    clearSession('tenant');
  }
}

/** The platform realm has no revocation route; the local half is all there is. */
export function platformSignOut(): void {
  clearSession('platform');
}
