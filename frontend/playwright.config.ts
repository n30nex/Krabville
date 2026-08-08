import { defineConfig } from "@playwright/test";

declare const process: { env: Record<string, string | undefined> };

const baseURL = process.env.KRABVILLE_E2E_URL ?? "http://127.0.0.1:18890";
const executablePath = process.env.KRABVILLE_CHROMIUM_PATH;

const viewports = [
  [375, 812],
  [800, 480],
  [1024, 600],
  [1366, 768],
  [1920, 1080],
] as const;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: "list",
  use: {
    baseURL,
    browserName: "chromium",
    headless: true,
    launchOptions: executablePath ? { executablePath } : undefined,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    ...viewports.map(([width, height]) => ({
      name: `${width}x${height}`,
      use: {
        viewport: { width, height },
        deviceScaleFactor: 1,
        hasTouch: width <= 800,
        isMobile: width <= 480,
      },
    })),
    {
      name: "800x480-reduced-motion",
      use: {
        viewport: { width: 800, height: 480 },
        deviceScaleFactor: 1,
        hasTouch: true,
      },
    },
  ],
});
