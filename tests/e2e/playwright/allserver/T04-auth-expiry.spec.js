/**
 * TASK-113 / T04 — B's session expires; only B is gated, A remains.
 *
 * Plan: start with A + B authenticated. Clear B's session cookie +
 * localStorage entry, reload, and assert that the picker shows B as
 * "needs-auth" while A's row is still clickable and the dashboard still
 * renders A's hosts.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T04 B session expires — A stays live, B is gated', async ({ page, context }) => {
  const { servers } = await mockServer(page, { count: 2 });
  await gotoWithAutoSign(page, '/');

  // Pick A first so we can confirm it survives B going down.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: new RegExp(`^${servers[0].server_name}$`) }).click();
  await expect(chip).toHaveText(servers[0].server_name, { timeout: 5_000 });

  // Simulate B's session expiring: clear the per-server auth state and
  // reload so the next getServerAuthState probe reports 'needs-auth' for B.
  await page.evaluate(() => {
    Object.keys(localStorage)
      .filter((k) => /server|auth/i.test(k))
      .forEach((k) => localStorage.removeItem(k));
    document.cookie.split(';').forEach((c) => {
      const name = c.split('=')[0].trim();
      if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
    });
  });
  await page.reload();

  // Re-open the picker; A is still listed, B now shows the lock / "needs auth" hint.
  const chip2 = page.locator('button[aria-haspopup="true"]').first();
  await chip2.click();
  const popover2 = page.locator('.MuiPopover-paper').first();
  await expect(popover2.getByText('All servers', { exact: true })).toBeVisible();
  // TODO: assert Lock icon visible for B's row, and absent for A.
  test.skip('requires the per-server auth-state probe to flip on cookie clear', async () => {
    // Live infra needed: the local backend must reject a probe after the
    // session is cleared while still serving A. Mock layer doesn't model
    // the cookie state because the route() handler ignores cookies.
  });
});