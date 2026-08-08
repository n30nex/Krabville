import { defineConfig } from "vite";

export default defineConfig({
  build: {
    target: "es2022",
    sourcemap: false,
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 1300,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:18890",
      "/reports": "http://127.0.0.1:18890",
      "/healthz": "http://127.0.0.1:18890",
    },
  },
});
