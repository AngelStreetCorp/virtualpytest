const { defineConfig } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

// Default so the config still loads in IDE test explorers; run_e2e_*.sh enforce E2E_BASE_URL for real runs.
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5073';
const storageStatePath = './playwright/.auth/user.json';

// Ensure the auth directory exists
const authDir = path.dirname(storageStatePath);
if (!fs.existsSync(authDir)) {
  fs.mkdirSync(authDir, { recursive: true });
}

// Only use storageState if the file exists
const hasStorageState = fs.existsSync(storageStatePath);

// GitHub Actions sets CI=true on every job (hosted AND self-hosted); on CI
// we let a single page-level flake pass on retry-2 instead of failing the
// whole LAN runner's e2e-* job. A real product bug still fails all three
// attempts. Local keeps retries=0 so devs see flakes immediately.
const isCI = process.env.CI === 'true' || process.env.CI === '1';

module.exports = defineConfig({
  testDir: '.',
  testMatch: ['specs/**/*.spec.js', 'allserver/**/*.spec.js'],
  outputDir: './test-results',
  timeout: 45_000,
  retries: isCI ? 2 : 0,
  expect: {
    timeout: 12_000,
  },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: './playwright-report' }]],
  globalSetup: './global-setup.js',
  use: {
    baseURL: BASE_URL,
    ignoreHTTPSErrors: true,
    screenshot: 'on',
    trace: 'retain-on-failure',
    video: 'off',
    storageState: hasStorageState ? storageStatePath : undefined,
  },
});
