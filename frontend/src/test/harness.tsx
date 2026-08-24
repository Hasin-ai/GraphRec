import { render } from '@testing-library/react';
import type { RenderResult } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { QueryClient } from '@tanstack/react-query';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import type { RouteObject } from 'react-router-dom';
import type { ReactElement } from 'react';

/**
 * Renders a route the way the application does — inside a router with real
 * loaders and a real query client — rather than mounting the component
 * directly.
 *
 * That distinction matters for this console specifically. Every gate is a
 * loader, so a test that mounted the page component would be testing the page
 * with its guards removed, which is the one configuration that must never
 * exist.
 */
export function renderRoutes(
  routes: RouteObject[],
  initialEntries: string[] = ['/'],
  // The workflow tests pass the *same* client the loaders were built with, so
  // that a page reads what its guard already fetched instead of asking twice.
  client?: QueryClient,
): RenderResult & { router: ReturnType<typeof createMemoryRouter> } {
  const queryClient =
    client ??
    new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  const router = createMemoryRouter(routes, { initialEntries });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, router };
}

/** The common case: one page, at one address, with nothing else in the tree. */
export function renderPage(
  path: string,
  element: ReactElement,
  initialEntries: string[] = [path],
): ReturnType<typeof renderRoutes> {
  return renderRoutes([{ path, element }, { path: '*', element: <div>elsewhere</div> }], initialEntries);
}
