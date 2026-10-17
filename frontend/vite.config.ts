import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  resolve: { preserveSymlinks: true },
  server: { proxy: { "/api": { target: "http://127.0.0.1:9030", ws: true } } },
  test: { environment: "jsdom", globals: true },
});
