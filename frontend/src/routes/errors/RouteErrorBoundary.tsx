/**
 * One boundary, mounted on every layout, that turns whatever a loader threw
 * into one of the three error pages.
 *
 * It renders *inside* the active layout (§5), so a tenant user who hits a 404
 * keeps their sidebar and can carry on; only a failure in the layout's own
 * loader takes the whole shell down, and at that point there is no session to
 * draw a shell for anyway.
 *
 * The mapping is narrow on purpose. Anything that is not recognisably a gate
 * outcome becomes `/error` with a reference, rather than being rendered — an
 * unrecognised error is exactly the case where the console knows least about
 * what it is safe to say.
 */

import { isRouteErrorResponse, Navigate, useRouteError } from 'react-router-dom';
import { isApiError } from '../../api/errors';
import { FailurePage, ForbiddenPage, NotFoundPage } from './pages';

export function RouteErrorBoundary() {
  const error = useRouteError();

  // Gates 3 and 4, thrown by the guards as bare `Response`s.
  if (isRouteErrorResponse(error)) {
    if (error.status === 403) return <ForbiddenPage />;
    if (error.status === 404) return <NotFoundPage />;
    return <FailurePage reference={null} />;
  }

  if (isApiError(error)) {
    // A 401 that survived the client's refresh-and-retry means the session is
    // genuinely gone. That is not an error page, it is a sign-in.
    if (error.status === 401) return <Navigate to="/login" replace />;
    if (error.status === 403) return <ForbiddenPage />;
    if (error.status === 404) return <NotFoundPage />;
    return <FailurePage reference={error.reference} />;
  }

  return <FailurePage reference={null} />;
}
