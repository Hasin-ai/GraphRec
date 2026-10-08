import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// In development the console proxies /v1 to the API. The default matches the
// Compose host port (API_PORT=8010); override with VITE_API_PROXY for a bare uvicorn.
const apiProxy = process.env.VITE_API_PROXY ?? "http://localhost:8010";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Browser evidence and trace HTML must not trigger development page reloads.
    watch: { ignored: ['**/e2e-results/**', '**/e2e-screens/**'] },
    proxy: {
      "/v1": { target: apiProxy, changeOrigin: true },
      "/healthz": { target: apiProxy, changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules")) {
            return "vendor";
          }
          if (id.includes("/pages/marketing/") || id.includes("/marketing/")) {
            return "marketing";
          }
          if (id.includes("/pages/platform/")) {
            return "platform";
          }
          if (id.includes("/pages/tenant/")) {
            return "tenant";
          }
          if (id.includes("/pages/public/")) {
            return "auth";
          }
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: { jsdom: { url: "http://localhost/" } },
    setupFiles: "./src/test/setup.ts",
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    css: false,
  },
});
