/**
 * The one way the console talks to the control API.
 *
 * Four things happen here and nowhere else, which is the reason for the file:
 *
 * 1. **The bearer token is attached.** No component builds an `Authorization`
 *    header, so no component can forget to.
 * 2. **A 401 is refreshed once and retried once.** Access tokens last fifteen
 *    minutes and the console is a thing people leave open; without this, every
 *    other click after lunch would be a spurious sign-out. A second 401 after a
 *    successful refresh clears the session — retrying again would be a loop.
 * 3. **Every non-2xx becomes an `ApiError`** carrying the server's envelope, so
 *    routes never invent copy and boundaries can switch on `status`.
 * 4. **`X-Request-Id` is captured** and becomes the error's `reference` when the
 *    body carries none, which is how `/error` shows something traceable even
 *    for a failure that never reached the application (§10.3).
 *
 * The refresh is deliberately *not* pre-emptive. Refreshing on a timer means
 * the console decides when a token is stale, using a clock that may not be the
 * server's. Refreshing on a 401 means the server decides, which is the only
 * party that can be right about it.
 *
 * **No tenant identifier is ever sent** (NR-NF-02). There is no parameter here
 * that could carry one and no helper that takes one: tenant scope lives in the
 * token, the server reads it from there, and §13 forbids it appearing in a path.
 */

import { ApiError, toApiError } from './errors';
import type { Realm, SessionResponse } from './session';
import { clearSession, readAccessToken, readRefreshToken, store } from './session';

/** Same origin. In development, `vite.config.ts` proxies `/v1` to the API. */
const BASE = '';

const REFRESH_PATH: Record<Realm, string | null> = {
  tenant: '/v1/auth/refresh',
  // The platform realm issues sessions but exposes no refresh route: an
  // operator's session ends and they sign in again. Attempting a refresh that
  // does not exist would turn every expiry into a 404 inside the console's own
  // error handling, so the absence is written down rather than discovered.
  platform: null,
};

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  /** Merged over the defaults; used for `Idempotency-Key` on submissions. */
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** `false` for sign-in, registration and recovery, which carry no token. */
  authenticated?: boolean;
}

/**
 * One in-flight refresh per realm, shared.
 *
 * Without this, a page that fires six queries on mount and finds the token
 * expired sends six refreshes. Refresh tokens are single-use and rotate, so
 * five of the six present a token the first has already superseded — which the
 * backend correctly reads as evidence of theft and answers by revoking the
 * family. The console would sign itself out by being busy.
 */
const inFlight = new Map<Realm, Promise<string | null>>();

async function refresh(realm: Realm): Promise<string | null> {
  const existing = inFlight.get(realm);
  if (existing) return existing;

  const path = REFRESH_PATH[realm];
  const refreshToken = readRefreshToken(realm);
  if (!path || !refreshToken) {
    clearSession(realm);
    return null;
  }

  const attempt = (async () => {
    try {
      const response = await fetch(`${BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) {
        clearSession(realm);
        return null;
      }
      const issued = (await response.json()) as SessionResponse;
      return store(realm, issued).accessToken;
    } catch {
      // A network failure is not a signed-out session. Clearing here would sign
      // the user out because their connection dropped for a second.
      return null;
    } finally {
      inFlight.delete(realm);
    }
  })();

  inFlight.set(realm, attempt);
  return attempt;
}

async function send(
  path: string,
  options: RequestOptions,
  token: string | null,
): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers['Authorization'] = `Bearer ${token}`;

  return fetch(`${BASE}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
}

function unreachable(): ApiError {
  return new ApiError(0, {
    class: 'unavailable',
    code: 'network_unreachable',
    reason:
      'The console could not reach the service. Check your connection and try again — ' +
      'nothing was submitted.',
    reference: 'network',
    field_errors: [],
    retryable: true,
    retry_after_seconds: null,
  });
}

export async function request<T>(
  realm: Realm,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const authenticated = options.authenticated ?? true;
  let token = authenticated ? readAccessToken(realm) : null;

  // A reloaded tab has a refresh token and no access token. Exchanging first is
  // cheaper than sending a request that is certain to 401.
  if (authenticated && !token && readRefreshToken(realm)) {
    token = await refresh(realm);
  }

  let response: Response;
  try {
    response = await send(path, options, token);
  } catch {
    // `fetch` rejects only for network-level failures. Presenting that as an
    // envelope keeps every caller on one error type.
    throw unreachable();
  }

  if (response.status === 401 && authenticated && token) {
    token = await refresh(realm);
    if (token) {
      try {
        response = await send(path, options, token);
      } catch {
        throw unreachable();
      }
    }
  }

  if (!response.ok) {
    const error = await toApiError(response);
    if (error.status === 401 && authenticated) clearSession(realm);
    throw error;
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Bound helpers, so a route reads `tenantApi.get('/v1/products')`. */
function realmClient(realm: Realm) {
  return {
    realm,
    get: <T>(path: string, options?: RequestOptions) =>
      request<T>(realm, path, { ...options, method: 'GET' }),
    post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
      request<T>(realm, path, { ...options, method: 'POST', body }),
    patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
      request<T>(realm, path, { ...options, method: 'PATCH', body }),
    put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
      request<T>(realm, path, { ...options, method: 'PUT', body }),
    delete: <T>(path: string, options?: RequestOptions) =>
      request<T>(realm, path, { ...options, method: 'DELETE' }),
  };
}

export const tenantApi = realmClient('tenant');
export const platformApi = realmClient('platform');

/** For sign-in, registration, invitation acceptance and recovery. */
export function anonymous<T>(path: string, body: unknown): Promise<T> {
  return request<T>('tenant', path, { method: 'POST', body, authenticated: false });
}
