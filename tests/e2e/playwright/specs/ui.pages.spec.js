/**
 * ui.pages.spec.js — Full page coverage: navigate every route, screenshot, check for JS errors.
 *
 * Goals:
 *   1. Visit every accessible page in the app
 *   2. Capture a full-page screenshot per page
 *   3. Fail if the page shows an error boundary ("Something went wrong")
 *   4. Fail if the page shows a doc loading error ("Error Loading Documentation")
 *   5. Collect console errors and attach them to the test report
 *
 * Run:
 *   E2E_BASE_URL=https://... E2E_AUTO_SIGN_TOKEN=... npx playwright test specs/ui.pages.spec.js
 */

const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('./_navigate');

// All navigable routes in the app (skipping auth-only, legacy redirects, and external embed pages)
const PAGES = [
  { name: 'Dashboard',              path: '/' },
  { name: 'Device Control',         path: '/device-control' },
  { name: 'AI Agent',               path: '/ai-agent' },
  { name: 'Agent Dashboard',        path: '/agent-dashboard' },
  { name: 'Test Builder',           path: '/builder/test-builder' },
  { name: 'Campaign Builder',       path: '/builder/campaign-builder' },
  { name: 'Test Cases',             path: '/test-plan/test-cases' },
  { name: 'Campaigns',              path: '/test-plan/campaigns' },
  { name: 'Requirements',           path: '/test-plan/requirements' },
  { name: 'Coverage',               path: '/test-plan/coverage' },
  { name: 'Run Tests',              path: '/test-execution/run-tests' },
  { name: 'Build Campaign',         path: '/test-execution/build-campaign' },
  { name: 'Monitor Tests',          path: '/test-execution/monitor-tests' },
  { name: 'Test Reports',           path: '/test-results/reports' },
  { name: 'Model Reports',          path: '/test-results/model-reports' },
  { name: 'Dependency Report',      path: '/test-results/dependency-report' },
  { name: 'Monitoring Incidents',   path: '/monitoring/incidents' },
  { name: 'Heatmap',                path: '/monitoring/heatmap' },
  { name: 'AI Queue',               path: '/monitoring/ai-queue' },
  { name: 'Docs Get Started',       path: '/docs/get-started' },
  { name: 'Docs Get Started',       path: '/docs/get-started' },   // section renamed from quickguide (TASK-15)
  { name: 'Docs FAQ',               path: '/docs/faq' },
  { name: 'Docs Features',          path: '/docs/features' },
  { name: 'Docs User Guide',        path: '/docs/user-guide' },
  { name: 'Docs Technical',         path: '/docs/technical' },
  { name: 'Docs Screenshots',       path: '/docs/screenshots' },
  { name: 'Docs Videos',            path: '/docs/videos' },
  { name: 'API Documentation',      path: '/docs/api' },
  { name: 'Grafana Dashboard',      path: '/grafana-dashboard' },
  { name: 'Langfuse Dashboard',     path: '/langfuse-dashboard' },
  { name: 'Postman Workspaces',     path: '/api/workspaces' },
  { name: 'Jira Integration',       path: '/integrations/jira' },
  { name: 'User Interface',         path: '/configuration/interface' },
  { name: 'Models',                 path: '/configuration/models' },
  { name: 'Settings',               path: '/configuration/settings' },
  { name: 'Code Deployment',        path: '/configuration/code-deployment' },
  { name: 'CICD Reports',           path: '/test-results/cicd-reports' },
  // Optional-feature pages (features/*/frontend/routes.tsx). Keep in sync with the route
  // inventory in docs/agent/validation/TESTING.md — nothing enforces it, and a feature page
  // that is never listed here is never swept. A disabled feature simply 404s, which this
  // spec treats as a pass (no error boundary), so these rows are safe on a trimmed build.
  { name: 'QuickTest Builder',      path: '/builder/quick-test' },
  { name: 'Virtual Scripts',        path: '/builder/virtual-scripts' },
  { name: 'Run CICD',               path: '/test-execution/cicd' },
  { name: 'Test Prompt',            path: '/test-prompt' },
  // Parameterised feature route — needs a concrete host/device. host-clone-1 is
  // VirtualPyTest's own device host and runs vpt-avq.service (see FEATURES.md).
  { name: 'AVQ Device',             path: '/monitoring/avq/host-clone-1/host' },
  { name: 'Status',                 path: '/status' },
];

for (const { name, path } of PAGES) {
  test(`Page: ${name} (${path})`, async ({ page }) => {
    const consoleErrors = [];

    // Collect console errors (ignore known benign warnings)
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        // Filter out known non-actionable noise
        if (
          text.includes('favicon') ||
          text.includes('net::ERR_') ||
          text.includes('ResizeObserver') ||
          text.includes('Extension context')
        ) return;
        consoleErrors.push(text);
      }
    });

    await gotoWithAutoSign(page, path);

    // Wait for the page to settle (network idle or 3s, whichever first). Pages with a live
    // socket/stream (Agent Dashboard, Monitor Tests…) never reach idle; without the explicit
    // timeout this waited the full 30 s default and blew the 45 s test budget.
    await page.waitForLoadState('networkidle', { timeout: 3_000 }).catch(() => {});

    // Screenshot
    await page.screenshot({
      path: `screenshots/${name.replace(/[^a-zA-Z0-9]/g, '_')}.png`,
      fullPage: true,
    });

    // Check for error boundary
    const errorBoundary = page.getByText('Something went wrong', { exact: false });
    await expect(errorBoundary, `Error boundary visible on ${name}`).not.toBeVisible();

    // Check for doc loading error
    const docError = page.getByText('Error Loading Documentation', { exact: false });
    await expect(docError, `Doc loading error visible on ${name}`).not.toBeVisible();

    // Check for the generic "Invalid documentation response" error
    const invalidDocError = page.getByText('Invalid documentation response', { exact: false });
    await expect(invalidDocError, `Invalid doc response on ${name}`).not.toBeVisible();

    // Check for a backend-communication failure banner. "Failed to fetch" is the
    // browser's native error when an API request never reaches the server (backend
    // down / not responding). The page itself still renders (no error boundary), so
    // without this check a page that loaded but displayed no data passes green — which
    // is exactly the false-success we want to catch.
    const fetchError = page.getByText('Failed to fetch', { exact: false }).first();
    await expect(
      fetchError,
      `Backend "Failed to fetch" banner visible on ${name} — server not responding`,
    ).not.toBeVisible();

    // Attach console errors to the report for visibility — but don't hard-fail on them
    // (some pages have known background errors from optional services like Grafana/Langfuse)
    if (consoleErrors.length > 0) {
      console.warn(`[${name}] Console errors:\n  ${consoleErrors.join('\n  ')}`);
    }
  });
}
