// Playwright config for the TASK-42 mocked-API spec (scripts/task42/run_playwright.sh).
// No globalSetup: the spec intercepts every /server/** call and seeds its own session,
// so it needs no auto-sign token and never reaches a real backend.
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './specs',
  testMatch: /task42-.*\.spec\.ts$/,
  // Runtime artifacts stay outside the checkout (CONTRACTS §23).
  outputDir: process.env.TASK42_PW_OUTPUT || require('path').join(require('os').tmpdir(), 'task42-playwright'),
  timeout: 45_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    // vite preview serves HTTPS with a self-signed certificate (basicSsl plugin).
    ignoreHTTPSErrors: true,
    baseURL: process.env.E2E_BASE_URL || 'https://127.0.0.1:4719',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
  },
});
