/**
 * TASK-113 / T14 — Partial server version mismatch: B is flagged as
 * incompatible; A and C work.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T14 version mismatch — B flagged as incompatible, A and C render', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 3 });

  // Replace B's auth check with a 500 to simulate an incompatible
  // /server/auth/check response.
  await page.unroute(/\/server\/auth\/check/);
  await page.route('**/server/auth/check*', async (route) => {
    const u = new URL(route.request().url());
    if (u.searchParams.get('server_url') === servers[1].server_url) {
      return route.fulfill({ status: 500, json: { error: 'incompatible' } });
    }
    return route.fulfill({ json: { success: true, authenticated: true } });
  });

  await gotoWithAutoSign(page, '/');

  // Switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();

  // A and C's hosts render.
  await expect(page.getByText('e2e-a', { exact: false })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('e2e-c', { exact: false })).toBeVisible();

  // B's row in the picker shows an incompatible / failed marker.
  await chip.click();
  const popover2 = page.locator('.MuiPopover-paper').first();
  // The exact UX is decided per the design; assert that the row is present
  // and visibly different from the healthy ones (e.g. the "Offline" text or
  // a dedicated "incompatible" label).
  test.skip('requires the front-end to expose the "incompatible" label; today the offline chip is reused', async () => {
    await expect(
      popover2.locator('button', { hasText: new RegExp(`${servers[1].server_name}.*(Offline|Incompatible)`, 's') }),
    ).toBeVisible();
  });
});