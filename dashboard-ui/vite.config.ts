/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    // Backend serves the bundle from src/bot/dashboard/v2/static/dist/.
    outDir: path.resolve(__dirname, "../src/bot/dashboard/v2/static/dist"),
    emptyOutDir: true,
    sourcemap: true,
    target: "es2022",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ws": {
        target: "ws://127.0.0.1:8765",
        ws: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
