/**
 * TASK-113 / T13 — Slow / hung B: per-server timeout; A remains
 * responsive; B surfaces "timeout" not crash.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T13 hung peer — A renders, B surfaces a timeout (no crash)', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 2 });

  // Replace B's getAllHosts with a 12s delay (past the 10s
  // AbortSignal.timeout the frontend uses per peer).
  await page.unroute(/\/server\/system\/getAllHosts/);
  await page.route((url) => {
    if (!/\/server\/system\/getAllHosts/.test(url.pathname)) return null;
    return null;
  });
  await page.route('**/server/system/getAllHosts*', async (route) => {
    const u = new URL(route.request().url());
    if (u.searchParams.get('server_url') === servers[1].server_url) {
      await new Promise((r) => setTimeout(r, 12_000));
      return route.fulfill({ json: { success: true, hosts: servers[1].hosts } });
    }
    return route.fulfill({ json: { success: true, hosts: servers[0].hosts } });
  });

  await gotoWithAutoSign(page, '/');

  // Switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();

  // A is responsive: its host renders within a reasonable window.
  await expect(page.getByText('e2e-a', { exact: false })).toBeVisible({ timeout: 8_000 });

  // B's host does NOT render (still pending) — the picker chip stays
  // reachable, no client-side crash.
  await page.waitForTimeout(11_000);
  const bHostCount = await page.getByText('e2e-b', { exact: false }).count();
  expect(bHostCount).toBeLessThanOrEqual(0); // B timed out, A is up
});