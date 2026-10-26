/**
 * TASK-113 / T19 — Stream auth negative: an invalid credential cannot
 * control / watch a forbidden device.
 *
 * The browser is the only client of every server. The destination
 * server's own session check (cookie + JWT) is the gate. There is no
 * shared credential, no token forwarding.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T19 invalid credential on B — stream/control refused, not silently watched', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 2 });

  // Mock B's HLS / control endpoints to return 401.
  await page.route('**/host/stream/**', async (route) => {
    const u = new URL(route.request().url());
    if (u.origin === servers[1].server_url) {
      return route.fulfill({ status: 401, json: { success: false, error: 'unauthorized' } });
    }
    return route.fulfill({ json: { success: true } });
  });
  await page.route('**/server/control/**', async (route) => {
    const u = new URL(route.request().url());
    if (u.origin === servers[1].server_url) {
      return route.fulfill({ status: 401, json: { success: false, error: 'unauthorized' } });
    }
    return route.fulfill({ json: { success: true } });
  });

  await gotoWithAutoSign(page, '/');

  // Switch to B and open a device.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: new RegExp(`^${servers[1].server_name}$`) }).click();
  await expect(chip).toHaveText(servers[1].server_name);

  // The device page surfaces the auth failure (the HLS player shows an
  // error overlay, the controls are disabled, or both).
  test.skip('requires a real B device to mount a video tag; mock layer returns 401 but the page is in a static state', async () => {
    const video = page.locator('video').first();
    if (await video.count()) {
      // The HLS.js error event must fire; this depends on the runtime.
      await page.waitForTimeout(2_000);
    }
    // The "needs auth" prompt is the canonical UX. Assert it shows.
    await expect(page.getByText(/sign in to use this server|Different login/i)).toBeVisible();
  });
});