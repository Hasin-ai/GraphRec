/**
 * Where session tokens live, and why they live there.
 *
 * `docs/BUILD_PROMPT.md` §10.3 sets the rule and this module obeys it
 * literally: **access token in memory only; refresh token in `sessionStorage`;
 * never `localStorage`.** The reasoning is worth restating because the easy
 * mistake is to "improve" it later:
 *
 * * An access token in memory dies with the tab. It is the credential that
 *   actually authorizes requests, and there is no version of leaving it on disk
 *   that is better than losing it on reload.
 * * A refresh token in `sessionStorage` survives a reload of the same tab and
 *   nothing else. `localStorage` would survive the browser being closed and
 *   reopened a week later, and would be shared across every tab and every other
 *   app on the origin — a longer-lived credential in a wider-reaching store,
 *   which is the wrong direction on both axes.
 * * An `HttpOnly` cookie would be better than either, and is a backend change
 *   first: `SessionResponse` returns both tokens in the body and sets no cookie.
 *   When that changes, this module is the only frontend file that has to.
 *
 * Two realms, two slots. A platform operator is not a tenant user (§4), and an
 * operator who also administers a tenant of their own is ordinary — a single
 * key would make signing in to one realm sign the other out.
 */

export type Realm = 'tenant' | 'platform';

export interface StoredSession {
  accessToken: string;
  /** ISO-8601, from `SessionResponse.expires_at`. */
  expiresAt: string;
  refreshToken: string;
  refreshExpiresAt: string;
}

const KEYS: Record<Realm, string> = {
  tenant: 'graphrec.refresh.tenant',
  platform: 'graphrec.refresh.platform',
};

/** Fired on every change, so the React tree stays in agreement with the store. */
const CHANGE = 'graphrec:session';

/**
 * The access token half. A module-level map and not React state: the client in
 * `client.ts` reads it from outside any component, and a loader that ran before
 * the tree mounted would otherwise have nothing to read.
 */
const access = new Map<Realm, { token: string; expiresAt: string }>();

interface PersistedHalf {
  refreshToken: string;
  refreshExpiresAt: string;
}

function persistent(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    // Blocked by a privacy setting or a sandboxed frame. The console still
    // works for the length of one page view; it just cannot survive a reload.
    return null;
  }
}

function announce(): void {
  window.dispatchEvent(new Event(CHANGE));
}

function readHalf(realm: Realm): PersistedHalf | null {
  const raw = persistent()?.getItem(KEYS[realm]);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PersistedHalf;
    // A half-written or hand-edited entry counts as no session rather than as a
    // session with undefined fields, which would fail later and further from
    // the cause.
    return typeof parsed.refreshToken === 'string' ? parsed : null;
  } catch {
    return null;
  }
}

export function readAccessToken(realm: Realm): string | null {
  return access.get(realm)?.token ?? null;
}

export function readRefreshToken(realm: Realm): string | null {
  return readHalf(realm)?.refreshToken ?? null;
}

/**
 * Whether this realm has anything to try with.
 *
 * True with only a refresh token and no access token — that is exactly the
 * state a reloaded tab is in, and the first request will exchange one for the
 * other. A guard that demanded an access token here would sign the user out on
 * every refresh of the page.
 */
export function hasSession(realm: Realm): boolean {
  return access.has(realm) || readHalf(realm) !== null;
}

export function clearSession(realm: Realm): void {
  access.delete(realm);
  persistent()?.removeItem(KEYS[realm]);
  announce();
}

export function onSessionChange(listener: () => void): () => void {
  window.addEventListener(CHANGE, listener);
  // `storage` fires in the *other* tabs of the same session, which is how
  // signing out here signs out there. It does not fire in the tab that made the
  // change; that is what the event above is for.
  window.addEventListener('storage', listener);
  return () => {
    window.removeEventListener(CHANGE, listener);
    window.removeEventListener('storage', listener);
  };
}

/** The shape `POST /v1/auth/sign-in` and `/v1/auth/refresh` both return. */
export interface SessionResponse {
  access_token: string;
  expires_at: string;
  refresh_token: string;
  refresh_expires_at: string;
  token_type?: string;
}

export function store(realm: Realm, response: SessionResponse): StoredSession {
  access.set(realm, { token: response.access_token, expiresAt: response.expires_at });
  persistent()?.setItem(
    KEYS[realm],
    JSON.stringify({
      refreshToken: response.refresh_token,
      refreshExpiresAt: response.refresh_expires_at,
    } satisfies PersistedHalf),
  );
  announce();
  return {
    accessToken: response.access_token,
    expiresAt: response.expires_at,
    refreshToken: response.refresh_token,
    refreshExpiresAt: response.refresh_expires_at,
  };
}

/** Test seam. Nothing in `src/` outside the tests calls this. */
export function resetSessionsForTest(): void {
  access.clear();
  for (const key of Object.values(KEYS)) persistent()?.removeItem(key);
}
