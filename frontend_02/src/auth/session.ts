import type { AuthTokenPair, TenantUserRole } from "../api/types";

/**
 * Two realms, one store. A tenant session is the token pair returned by
 * POST /v1/auth/login (or /setup-password); a platform session is the shared
 * PLATFORM_ADMIN_TOKEN, validated against GET /v1/platform/status.
 *
 * Sessions live in sessionStorage: they survive a reload, end with the tab, and
 * never reach another origin. The 15-minute access token is renewed with the
 * single-use refresh token (POST /v1/auth/refresh, rotated on every use); the
 * session ends only when refresh fails or the user signs out.
 */
export interface TenantSession {
  kind: "tenant";
  email: string;
  role: TenantUserRole;
  scopes: string[];
  accessToken: string;
  /** Single-use refresh token; replaced on every refresh. */
  refreshToken?: string;
  expiresAt: number;
  signedInAt: number;
}

export interface PlatformSession {
  kind: "platform";
  token: string;
  signedInAt: number;
}

const TENANT_KEY = "graphrec.session.tenant";
const PLATFORM_KEY = "graphrec.session.platform";
export const SESSION_EVENT = "graphrec:session";

function read<T>(key: string): T | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown | null): void {
  try {
    if (value === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: the in-memory copy below still works for this page */
  }
  window.dispatchEvent(new Event(SESSION_EVENT));
}

let tenantCache: TenantSession | null | undefined;
let platformCache: PlatformSession | null | undefined;

export function getTenantSession(): TenantSession | null {
  if (tenantCache === undefined) tenantCache = read<TenantSession>(TENANT_KEY);
  // An expired access token is still a live session while it can be refreshed.
  if (tenantCache && tenantCache.expiresAt <= Date.now() && !tenantCache.refreshToken) {
    tenantCache = null;
    write(TENANT_KEY, null);
  }
  return tenantCache;
}

export function setTenantSession(email: string, pair: AuthTokenPair, signedInAt: number = Date.now()): TenantSession {
  const session: TenantSession = {
    kind: "tenant",
    email,
    role: pair.user_role,
    scopes: pair.scopes,
    accessToken: pair.access_token,
    refreshToken: pair.refresh_token,
    expiresAt: Date.now() + pair.expires_in * 1000,
    signedInAt,
  };
  tenantCache = session;
  write(TENANT_KEY, session);
  return session;
}

export function clearTenantSession(): void {
  tenantCache = null;
  write(TENANT_KEY, null);
}

/** D13: an explicit sign-out must not hand the next user this user's last page. */
let signedOutExplicitly = false;
export function markExplicitSignOut(): void { signedOutExplicitly = true; }
export function consumeExplicitSignOut(): boolean { const value = signedOutExplicitly; signedOutExplicitly = false; return value; }

export function getPlatformSession(): PlatformSession | null {
  if (platformCache === undefined) platformCache = read<PlatformSession>(PLATFORM_KEY);
  return platformCache;
}

export function setPlatformSession(token: string): PlatformSession {
  const session: PlatformSession = { kind: "platform", token, signedInAt: Date.now() };
  platformCache = session;
  write(PLATFORM_KEY, session);
  return session;
}

export function clearPlatformSession(): void {
  platformCache = null;
  write(PLATFORM_KEY, null);
}

export function hasScope(session: TenantSession | null, scope: string): boolean {
  return !!session && session.scopes.includes(scope);
}

export function roleLabel(role: TenantUserRole): string {
  return role === "tenant_administrator" ? "tenant administrator" : "tenant developer";
}

/** Display-only identity from the issued token. The API still verifies every request. */
export function sessionTenantId(session: TenantSession): string | null {
  try {
    const payload = session.accessToken.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(atob(payload)) as { tid?: unknown };
    return typeof claims.tid === "string" ? claims.tid : null;
  } catch { return null; }
}
