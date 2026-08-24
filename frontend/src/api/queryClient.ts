import { QueryClient } from '@tanstack/react-query';
import { isApiError } from './errors';

/**
 * One client for the application, and one for each test.
 *
 * The retry policy is the only interesting setting. A 4xx is the server's
 * answer and retrying it is noise — three attempts at a 403 produce three audit
 * rows and delay the redirect by a second. A 5xx or a network failure is worth
 * one more try, because the common cause is a single unlucky request rather
 * than a broken service.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          if (isApiError(error) && error.status >= 400 && error.status < 500) return false;
          return failureCount < 1;
        },
        // The console is an operations tool: the numbers on screen should be
        // current when the reader comes back to the tab.
        refetchOnWindowFocus: true,
        staleTime: 30 * 1000,
      },
      mutations: { retry: false },
    },
  });
}
