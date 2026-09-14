const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('./_navigate');

test.describe('UI Smoke - Critical Pages', () => {
  test('1. Dashboard displays core server summary', async ({ page }) => {
    await gotoWithAutoSign(page, '/');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByText('Registered Servers', { exact: false })).toBeVisible();
  });

  test('2. Device Control displays host/device controls', async ({ page }) => {
    await gotoWithAutoSign(page, '/device-control');
    await expect(page.getByRole('heading', { name: 'Device', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Edit' })).toBeVisible();
  });

  test('3. Monitoring Incidents displays incident summary tables', async ({ page }) => {
    await gotoWithAutoSign(page, '/monitoring/incidents');
    await expect(page.getByRole('heading', { name: 'Incident Summary' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'In Progress' })).toBeVisible();
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
    // Verify the page heading is visible (page title is "Interface") - use exact to avoid strict mode violation
    await expect(page.getByRole('heading', { name: 'Interface', exact: true })).toBeVisible();
    // Verify the Add UI button is visible (page is functional)
    await expect(page.getByRole('button', { name: 'Add UI' })).toBeVisible();
  });

  test('7. API docs page displays interactive docs controls', async ({ page }) => {
    await gotoWithAutoSign(page, '/docs/api');
    await expect(page.getByRole('heading', { name: /API Documentation/i })).toBeVisible();
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
