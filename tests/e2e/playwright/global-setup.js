/**
 * Global setup for Playwright E2E tests.
 * This runs once before all tests.
 * E2E uses token-only auto-sign auth (no username/password login flow).
 */
const { chromium } = require('playwright');

module.exports = async (config) => {
  // Support both old and new Playwright config structures
  // config can be undefined in some versions
  const cfg = config || {};
  const baseURL = cfg.use?.baseURL || cfg.projects?.[0]?.use?.baseURL || process.env.E2E_BASE_URL || 'http://localhost:5073';
  const autoSignToken = process.env.E2E_AUTO_SIGN_TOKEN;

  if (!autoSignToken) {
    throw new Error(
      'E2E_AUTO_SIGN_TOKEN is required for Playwright global setup. ' +
      'E2E auth is token-only and does not use username/password login.'
    );
  }

  const autoSignUrl = baseURL.replace(/\/$/, '') + `/?auto_signed=${encodeURIComponent(autoSignToken)}`;
  // Token redacted: global-setup output is attached to the published report too.
  console.log(`🔐 Auto-sign enabled - activating session via token URL: ${autoSignUrl.replace(/(auto_signed=)[^&]+/, '$1***')}`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  try {
    await page.goto(autoSignUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1500);
  } catch (error) {
    console.log('⚠️  Auto-sign activation error:', error.message);
  } finally {
    await context.storageState({ path: 'playwright/.auth/user.json' });
    await browser.close();
  }

  console.log('Global setup complete (auto-sign)');
};
