import { useMemo } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { createQueryClient } from './api/queryClient';
import { createRouter } from './router';

/**
 * The provider stack, and nothing else.
 *
 * The query client and the router are built once and memoised together,
 * because the router's loaders close over the client: rebuilding either alone
 * would leave loaders reading a cache nothing else writes to.
 */
export function App() {
  const { queryClient, router } = useMemo(() => {
    const client = createQueryClient();
    return { queryClient: client, router: createRouter(client) };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
