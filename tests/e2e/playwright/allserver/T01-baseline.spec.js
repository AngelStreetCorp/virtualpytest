/**
 * TASK-113 / T01 — Single-server baseline.
 *
 * Canary: the existing single-server UX must not change when ALL mode is
 * not engaged. The live deployment's single-server state is the natural
 * baseline: the picker chip shows the configured server's name, the
 * "All servers" row is present in the popover, and the dashboard
 * renders the configured host.
 *
 * Run with:
 *   E2E_BASE_URL=https://<node1> E2E_AUTO_SIGN_TOKEN=<token> \
 *     npx playwright test tests/e2e/playwright/allserver/T01-baseline.spec.js
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');

test('T01 single-server baseline — UX unchanged when scope.kind=single', async ({ page }) => {
  await gotoWithAutoSign(page, '/');

  // The scope picker chip is the first button[aria-haspopup="true"].
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await expect(chip).toBeVisible({ timeout: 15_000 });

  // The chip shows the configured server's name (not "All servers" and
  // not "No server") — single-server mode is the default.
  const chipText = (await chip.textContent())?.trim() ?? '';
  expect(chipText).not.toMatch(/all servers/i);
  expect(chipText).not.toMatch(/no server/i);
  expect(chipText.length).toBeGreaterThan(0);

  // Open the popover and assert the "All servers" row is present
  // (it should be — PR-C extension wired both pickers).
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await expect(popover).toBeVisible();
  await expect(popover.getByText('All servers', { exact: true })).toBeVisible();

  // The popover also lists at least the configured server. The label
  // in the chip is the display name (the SERVER_NAME from /etc/environment,
  // e.g. "Awesomation" or "vpt-pi1"); the popover shows the same display
  // name. Assert that the popover has more than one button row, which
  // is the canary that "All servers" + at least one server are both there.
  const popoverButtons = await popover.locator('button').allTextContents();
  const serverishRows = popoverButtons.filter(
    (t) => t.trim().length > 0 && t.trim() !== 'All' && t.trim() !== 'All servers',
  );
  expect(serverishRows.length).toBeGreaterThanOrEqual(1);
});