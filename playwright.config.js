// @ts-check
const { defineConfig, devices } = require("@playwright/test");

const port = Number(process.env.PLAYWRIGHT_PORT || 3101);
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${port}`;
const useExternalServer = process.env.PLAYWRIGHT_USE_EXTERNAL_SERVER === "1";

module.exports = defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
  ],
  webServer: useExternalServer
    ? undefined
    : {
        command: "npm run start:e2e",
        env: {
          DATABASE_URL: "sqlite:///tmp/e2e.sqlite3",
          DJANGO_ALLOWED_HOSTS: "127.0.0.1,localhost",
          DJANGO_DEBUG: "1",
          DJANGO_SECRET_KEY: "test_sk_playwright_local_only",
          PLAYWRIGHT_PORT: String(port),
        },
        reuseExistingServer: false,
        timeout: 20_000,
        url: baseURL,
      },
});
