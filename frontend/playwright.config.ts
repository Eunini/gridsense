import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.pw.ts",
  workers: 1,
  timeout: 40_000,
  use: {
    baseURL: "http://127.0.0.1:8788",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    launchOptions: process.env.BROWSER_EXECUTABLE
      ? { executablePath: process.env.BROWSER_EXECUTABLE }
      : {},
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    {
      name: "mobile",
      use: {
        viewport: { width: 390, height: 844 },
        isMobile: true,
        deviceScaleFactor: 1,
      },
    },
  ],
  webServer: {
    command: "uv run uvicorn gridsense.api:app --host 127.0.0.1 --port 8788",
    cwd: "..",
    url: "http://127.0.0.1:8788/api/health",
    reuseExistingServer: !process.env.CI,
  },
});
