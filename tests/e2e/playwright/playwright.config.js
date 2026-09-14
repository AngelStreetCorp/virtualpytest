const { defineConfig } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.E2E_BASE_URL || (() => { throw new Error('E2E_BASE_URL is required (e.g. https://your-server)'); })();
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
