/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5191,
    proxy: { "/api/demo": { target: "http://localhost:5190", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: true },
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
