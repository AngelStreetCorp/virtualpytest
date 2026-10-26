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

  // The saved storageState cannot carry an auto-sign session, and never could.
  // frontend/src/lib/autoSign.ts restores it from sessionStorage ONLY (deliberate, BUG-0392),
  // and Playwright's storageState captures localStorage but never sessionStorage. So the next
  // page load falls through to clearAutoSignSession() — wiping the very keys we just saved —
  // and ProtectedRoute redirects to /login. This setup used to look green while every spec
  // silently landed on the login page.
  //
  // So prove the token against the BACKEND, directly. Two things that look like verification but
  // are not:
  //   - Where the browser lands. The SPA sets isAuthenticated from the stored auto-sign flag, so
  //     a wrong token still routes to /dashboard and paints the full chrome; only /server/* 401s.
  //   - "Some /server/* call returned 2xx". The app talks to several servers, and public
  //     endpoints can answer 200 regardless of the token.
  // A direct X-Auto-Sign request to a protected endpoint is the only discriminating check.
  const probeUrl = `${baseURL.replace(/\/$/, '')}/server/agents/`;
  let probeStatus = 0;
  let probeBody = '';
  try {
    const res = await fetch(probeUrl, { headers: { 'X-Auto-Sign': autoSignToken } });
    probeStatus = res.status;
    probeBody = (await res.text()).slice(0, 200);
  } catch (error) {
    throw new Error(`auto-sign preflight could not reach ${probeUrl}: ${error.message}`);
  }

  if (probeStatus === 401 || probeStatus === 403) {
    throw new Error(
      `auto-sign preflight failed: ${probeUrl} answered ${probeStatus} with the X-Auto-Sign token. ` +
      `Either E2E_AUTO_SIGN_TOKEN does not match the server's AUTO_SIGN_TOKEN, or ` +
      `AUTO_SIGN_ENABLED is not true on that server. (body: ${probeBody})`
    );
  }
  if (probeStatus >= 400) {
    throw new Error(
      `auto-sign preflight got ${probeStatus} from ${probeUrl}, which this harness cannot ` +
      `interpret. Check the target server before trusting the E2E run. (body: ${probeBody})`
    );
  }
  console.log(`✅ Auto-sign verified (${probeUrl} → ${probeStatus})`);

  console.log(
    'Global setup complete (auto-sign).\n' +
    '⚠️  Specs MUST pass ?auto_signed=<token> on their FIRST page.goto() in the SAME tab —\n' +
    '    storageState cannot restore the session (sessionStorage is tab-scoped). Navigating\n' +
    '    afterwards in that same tab is fine. See docs/agent/validation/TESTING.md.'
  );
};
