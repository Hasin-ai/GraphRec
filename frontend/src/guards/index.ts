/**
 * Gates 1–4, as route loaders. Gate 5 is deliberately absent — see the bottom.
 *
 * The gates run in the order the backend runs them (`apps/control_api/deps.py`),
 * and the order is the security property rather than a style choice:
 *
 * 1. **Identity** — no session → `/login`.
 * 2. **Tenant state** — tenant not `active` → `/account/tenant-status`.
 * 3. **Role / permission** — role not permitted → `/403`.
 * 4. **Ownership** — a 404 from the API → `/404`, naming nothing.
 *
 * These are guards, not the authorization. The server decides; every one of
 * these checks is re-made there against the token, and a caller who edits the
 * bundle to skip them gains nothing but a different error message. What they
 * buy is that the console does not render a page it is about to be refused,
 * and — §13, explicitly — that a route is guarded by a **route guard** rather
 * than by a hidden button.
 *
 * Gate 5 is not here and must not be added here. Whether a *resource* is in a
 * state that permits an action is answered by the server in the `actions` and
 * `can_*` fields of the resource itself, and the console renders that as a
 * disabled control carrying the server's reason. A gate-5 guard would navigate,
 * and navigating away from a page because one button on it is unavailable is
 * the behaviour §13 forbids.
 */

import { redirect } from 'react-router-dom';
import type { QueryClient } from '@tanstack/react-query';
import { hasSession } from '../api/session';
import { isApiError } from '../api/errors';
import { meQuery, platformMeQuery, tenantQuery } from '../api/hooks/identity';
import type { Me, PlatformMe, TenantSummary } from '../api/hooks/identity';
import type { PlatformPermission, TenantRole } from '../lib/enums';

export interface TenantContext {
  me: Me;
  tenant: TenantSummary;
}

/**
 * Where to come back to after signing in.
 *
 * Carried in the query string rather than in storage, so that a link sent to
 * somebody who is not signed in still lands them where it pointed, and so that
 * nothing survives the sign-in it was not meant to.
 */
function loginRedirect(request: Request, to = '/login'): Response {
  const target = new URL(request.url);
  const next = `${target.pathname}${target.search}`;
  const search = next && next !== '/' ? `?next=${encodeURIComponent(next)}` : '';
  return redirect(`${to}${search}`);
}

/** Gate 1 for the tenant realm. */
export function requireTenantSession(request: Request): void {
  if (!hasSession('tenant')) throw loginRedirect(request);
}

/** Gate 1 for the platform realm. A separate realm gets a separate sign-in. */
export function requirePlatformSession(request: Request): void {
  if (!hasSession('platform')) throw loginRedirect(request, '/admin/login');
}

/**
 * Gates 1 and 2 together, which is what `TenantLayout` runs.
 *
 * The two identity reads are fetched in parallel and their failures are handled
 * differently, which is the whole subtlety of this function:
 *
 * * `/v1/tenant` is exempt from gate 2, so it answers for a suspended tenant.
 * * `/v1/me` is **not** exempt, so for a suspended tenant it answers 403
 *   `tenant_not_active`. That is not an error to surface; it is gate 2 firing,
 *   and the correct response is the redirect below rather than an error page.
 */
export async function tenantGuard(
  queryClient: QueryClient,
  request: Request,
): Promise<TenantContext> {
  requireTenantSession(request);

  let tenant: TenantSummary;
  try {
    tenant = await queryClient.fetchQuery(tenantQuery);
  } catch (error) {
    if (isApiError(error) && error.status === 401) {
      throw loginRedirect(request);
    }
    throw error;
  }

  // ------------------------------------------------------ gate 2
  if (tenant.status !== 'active') throw redirect('/account/tenant-status');

  try {
    const me = await queryClient.fetchQuery(meQuery);
    return { me, tenant };
  } catch (error) {
    if (isApiError(error) && error.status === 401) throw loginRedirect(request);
    if (isApiError(error) && error.code === 'tenant_not_active') {
      // The tenant changed state between the two reads. Rare, and the answer is
      // the same one gate 2 gives above rather than an error page.
      throw redirect('/account/tenant-status');
    }
    throw error;
  }
}

/**
 * The gate-2 landing page's own loader: session required, tenant state *not*.
 *
 * A tenant that has become active while this page was open should not be left
 * sitting on it, so the active case redirects back into the application.
 */
export async function tenantStatusGuard(
  queryClient: QueryClient,
  request: Request,
): Promise<TenantSummary> {
  requireTenantSession(request);
  try {
    const tenant = await queryClient.fetchQuery(tenantQuery);
    if (tenant.status === 'active') throw redirect('/home');
    return tenant;
  } catch (error) {
    if (error instanceof Response) throw error;
    if (isApiError(error) && error.status === 401) throw loginRedirect(request);
    throw error;
  }
}

/** Gate 3, tenant realm. Throws a `Response` the error boundary renders as /403. */
export function requireRole(me: Me, allowed: readonly TenantRole[]): void {
  if (!allowed.includes(me.role)) {
    throw new Response('Forbidden', { status: 403 });
  }
}

/** Gates 1 and 3 for the platform realm, in one loader. */
export async function platformGuard(
  queryClient: QueryClient,
  request: Request,
  required?: PlatformPermission,
): Promise<PlatformMe> {
  requirePlatformSession(request);

  let operator: PlatformMe;
  try {
    operator = await queryClient.fetchQuery(platformMeQuery);
  } catch (error) {
    if (isApiError(error) && error.status === 401) {
      throw loginRedirect(request, '/admin/login');
    }
    throw error;
  }

  // ------------------------------------------------------ gate 3
  if (required && !operator.permissions.includes(required)) {
    throw new Response('Forbidden', { status: 403 });
  }
  return operator;
}

/**
 * Gate 4. Turns "the API said 404" into the console's `/404`, naming nothing.
 *
 * A foreign resource must render `/404` and never `/403` (§13): a 403 on a
 * resource that belongs to someone else confirms that the resource exists,
 * which is precisely what tenant isolation is for. The server already answers
 * 404 for both "does not exist" and "is not yours"; this makes sure the console
 * does not undo that by rendering something more helpful.
 */
export function rethrowAsRouteError(error: unknown): never {
  if (isApiError(error) && error.status === 404) {
    throw new Response('Not found', { status: 404 });
  }
  if (isApiError(error) && error.status === 403) {
    throw new Response('Forbidden', { status: 403 });
  }
  throw error;
}
