import type { AuthTokenPair, TenantUserRole } from "../api/types";

/**
 * Two realms, one store. A tenant session is the token pair returned by
 * POST /v1/auth/login (or /setup-password); a platform session is the shared
 * PLATFORM_ADMIN_TOKEN, validated against GET /v1/platform/status.
 *
 * Sessions live in sessionStorage: they survive a reload, end with the tab, and
 * never reach another origin. The API has no refresh endpoint, so an expired
 * access token (401 token_expired) simply signs the user out.
 */
export interface TenantSession {
  kind: "tenant";
  email: string;
  role: TenantUserRole;
  scopes: string[];
  accessToken: string;
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
  if (tenantCache && tenantCache.expiresAt <= Date.now()) {
    tenantCache = null;
    write(TENANT_KEY, null);
  }
  return tenantCache;
}

export function setTenantSession(email: string, pair: AuthTokenPair): TenantSession {
  const session: TenantSession = {
    kind: "tenant",
    email,
    role: pair.user_role,
    scopes: pair.scopes,
    accessToken: pair.access_token,
    expiresAt: Date.now() + pair.expires_in * 1000,
    signedInAt: Date.now(),
  };
  tenantCache = session;
  write(TENANT_KEY, session);
  return session;
}

export function clearTenantSession(): void {
  tenantCache = null;
  write(TENANT_KEY, null);
}

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
