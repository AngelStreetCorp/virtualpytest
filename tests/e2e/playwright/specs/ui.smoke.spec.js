const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('./_navigate');

test.describe('UI Smoke - Critical Pages', () => {
  test('1. Dashboard displays core server summary', async ({ page }) => {
    await gotoWithAutoSign(page, '/');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    // After the Dashboard Tabs refactor (8a/9a area: feat(dashboard): page-tab cards),
    // the page opens straight on the Overview tab whose KPI tiles ("Pass rate",
    // "Running now", "Devices up", "Failures") are the core server summary now. Assert
    // one of them instead of the retired "System Stats" string, which lives only as a
    // stale i18n key on a code path the page no longer renders.
    await expect(page.getByText('Pass rate', { exact: true }).first()).toBeVisible();
  });

  test('2. Device Control displays host/device controls', async ({ page }) => {
    await gotoWithAutoSign(page, '/device-control');
    // The heading carries a count badge (e.g. "Device 6") so an exact-text match
    // against "Device" misses the accessible name; match the "Device" prefix
    // instead so the spec is robust to the badge count.
    await expect(page.getByRole('heading', { name: /^Device\b/ })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Edit' })).toBeVisible();
  });

  test('3. Monitoring Incidents displays incident summary tables', async ({ page }) => {
    await gotoWithAutoSign(page, '/monitoring/incidents');
    // Page title was changed from "Incident Summary" to "Alerts" in 4563c4746
    // (feat(incidents): restyle). Subtitle still starts with "Incidents the monitor opened…".
    await expect(page.getByRole('heading', { name: 'Alerts' })).toBeVisible();
    // The status tab is rendered as "In progress" (lowercase 'p') in MonitoringIncidents.tsx —
    // match it case-insensitively so the spec is robust to a future capitalisation tweak.
    await expect(page.getByRole('heading', { name: /In Progress/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Closed' })).toBeVisible();
  });

  test('4. Heatmap displays timeline and analysis sections', async ({ page }) => {
    await gotoWithAutoSign(page, '/monitoring/heatmap');
    await expect(page.getByRole('heading', { name: '24h Heatmap' })).toBeVisible();
    // Use first() to avoid strict mode violation — 'Devices' appears in header card (always)
    // and optionally in the HeatMapHistory table when reports exist
    await expect(page.getByText('Devices').first()).toBeVisible();
  });

  test('5. Run Tests displays script launcher', async ({ page }) => {
    await gotoWithAutoSign(page, '/test-execution/run-tests');
    await expect(page.getByRole('heading', { name: 'Run Tests' })).toBeVisible();
  });

  test('6. User Interface page loads correctly', async ({ page }) => {
    await gotoWithAutoSign(page, '/configuration/interface');
    // The page heading is `Interface (N)` (the count of registered UIs in the team),
    // not the bare "Interface" — match a regex so the spec survives the count changing.
    await expect(page.getByRole('heading', { name: /^Interface(\s*\(\d+\))?$/ })).toBeVisible();
    // Verify the Add UI button is visible (page is functional)
    await expect(page.getByRole('button', { name: 'Add UI' })).toBeVisible();
  });

  test('7. API docs page displays interactive docs controls', async ({ page }) => {
    await gotoWithAutoSign(page, '/docs/api');
    // After 568ffd069 + 09a6ef471 the page paint is owned by Documentation.tsx (the docs
    // shell renders ApiDocsView inside its card). The header bar reads the first H1 from
    // docs/api/README.md, which is "API Reference"; the previous text "API Documentation"
    // came from the removed standalone ApiDocumentation page.
    await expect(page.getByRole('heading', { name: /API Reference/i })).toBeVisible();
    // Page uses a dropdown selector, not tabs - verify the dropdown is present (use first() to avoid strict mode)
    await expect(page.locator('#doc-select').first()).toBeVisible();
    await expect(page.locator('iframe[title*="SERVER"], iframe[title*="APIs"], iframe').first()).toBeVisible();
  });

  test('7. API docs can switch to Script Management doc', async ({ page }) => {
    await gotoWithAutoSign(page, '/docs/api');
    await page.locator('#doc-select').click();
    await page.getByRole('option', { name: 'SERVER - Script' }).click();
    await expect(page.locator('iframe')).toBeVisible();
    const src = await page.locator('iframe').getAttribute('src');
    expect(src).toContain('server-script-management');
  });
});
