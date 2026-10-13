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

module.exports = defineConfig({
  testDir: './specs',
  outputDir: './test-results',
  timeout: 45_000,
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
