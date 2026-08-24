import { defineConfig } from 'vitest/config';

/**
 * Separate from `vite.config.ts` on purpose.
 *
 * Vitest 2 carries its own copy of Vite, so a single config that both typed
 * `test` and passed `plugins` would be handing a Vite 6 plugin to a Vite 5
 * type — structurally identical, nominally different, and a wall of
 * unresolvable variance errors. Splitting them means neither file has to know
 * about the other's Vite.
 *
 * No React plugin is needed here: esbuild compiles JSX from the `jsx` setting
 * in `tsconfig.json`, and Fast Refresh has nothing to refresh in a test run.
 */
export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
