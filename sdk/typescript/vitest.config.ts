import { defineConfig } from 'vitest/config';

/**
 * Node, not jsdom. The SDK has no browser build (see `README.md` — a bearer
 * credential with tenant-wide scope has no business in a page), so testing it
 * in a simulated one would be testing an environment it refuses to support.
 */
export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    restoreMocks: true,
  },
});
