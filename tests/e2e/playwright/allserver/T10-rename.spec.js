/**
 * TASK-113 / T10 — Server rename / URL change: the picker uses the URL
 * as identity, so a rename IS a new server; the user is prompted before
 * the new server replaces the old one.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T10 server rename — picker treats the new URL as a new server and prompts', async ({ page }) => {
  // First load: one server named "e2e-a".
  const { servers: initial } = await mockServer(page, { count: 1 });
  await gotoWithAutoSign(page, '/');

  // Now mutate the mock so the same logical server is reconfigured with
  // a different URL but the same name. The picker must surface a "this
  // server replaced previous" hint.
  await page.unroute(/\/server\/auth\/check/);
  await page.unroute(/\/server\/system\/getAllHosts/);
  await page.route(/\/server\/auth\/check/, (route) => route.fulfill({ json: { success: true, authenticated: true } }));
  await page.route(/\/server\/system\/getAllHosts/, (route) =>
    route.fulfill({
      json: {
        success: true,
        hosts: initial[0].hosts,
        servers: [{ ...initial[0], server_url: 'http://localhost:9999' }],
      },
    }),
  );

  await page.reload();
  await page.waitForLoadState('networkidle');

  // The picker should now show a "replaced" hint for the new URL. The
  // exact UX is decided in §E1; this spec asserts the picker surfaces
  // the new URL AND keeps the old entry.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await expect(popover).toBeVisible();

  test.skip('§E1 resolution pending: URL-as-identity is the default; rename prompt UX is open', async () => {
    await expect(popover.getByText(/localhost:9999/)).toBeVisible();
    // The hint or the diff is asserted once the design lands.
  });
});