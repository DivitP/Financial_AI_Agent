import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  retries: 0,
  workers: 2,
  use: {
    baseURL: "http://127.0.0.1:4179",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npx vite preview --config vite.config.ts --host 127.0.0.1 --port 4179 --strictPort",
    port: 4179,
    reuseExistingServer: false,
  },
});
