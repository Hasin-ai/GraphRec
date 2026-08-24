import { redirect } from 'react-router-dom';
import type { QueryClient } from '@tanstack/react-query';
import { platformGuard } from '../guards';
import { firstPermittedPlatformRoute } from '../layouts/nav';

/**
 * `/admin` is a redirect, not a page: to the first route this operator's
 * permissions open.
 *
 * There is no "platform overview" behind it, because the five permissions are
 * granted independently and there is no view that every operator is entitled
 * to. An operator holding none of them gets `/403` — terminal, as §7 requires,
 * since no retry will change it.
 */
export function adminIndexLoader(queryClient: QueryClient) {
  return async ({ request }: { request: Request }): Promise<Response> => {
    const operator = await platformGuard(queryClient, request);
    const destination = firstPermittedPlatformRoute(operator.permissions);
    if (!destination) throw new Response('Forbidden', { status: 403 });
    return redirect(destination);
  };
}
