import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "line",
  webServer: {
    command: "NEXT_PUBLIC_INTERNAL_AUTH_MODE=local NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev -- --hostname 127.0.0.1",
    env: { API_INTERNAL_URL: "http://localhost:8000", PILOT_ACCESS_USERNAME: "local-e2e", PILOT_ACCESS_PASSWORD: "local-e2e-disposable-password" },
    url: "http://localhost:3000",
    reuseExistingServer: true,
  },
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    httpCredentials: { username: "local-e2e", password: "local-e2e-disposable-password" },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
