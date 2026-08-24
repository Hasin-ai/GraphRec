import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * The application build. Tests are configured separately in `vitest.config.ts`
 * — see the note there for why the two files are not one.
 *
 * There is no path alias: every import in `src/` is relative, and an alias
 * would need `@types/node` here to resolve a directory for the sake of a few
 * `../`.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The console talks to the control API on the same origin so that nothing
    // in the client has to know a host name. In development that is this proxy;
    // in production it is a reverse proxy in front of both.
    proxy: {
      '/v1': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
