/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  // ECharts and AG Grid are split into their own lazily loaded chunks (see src/router.tsx).
  build: { chunkSizeWarningLimit: 1300 },
  test: { environment: "jsdom", globals: false },
});
