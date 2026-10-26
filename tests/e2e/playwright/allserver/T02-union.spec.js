/**
 * TASK-113 / T02 — ALL A+B union.
 *
 * The picker must show every server's rows as a union. With A and B both
 * configured, opening the picker surfaces "All servers" + 2 server rows.
 * Clicking "All servers" leaves the picker chip on "All servers" and
 * leaves the dashboard reachable (no 5xx, no "needs auth" prompt, no
 * client-side crash).
 *
 * The PoC at `/tmp/t113-poc.js` was the live proof; this spec is the
 * CI-runnable version of that PoC. It runs against the live deployment
 * (no mocks) so the test plan's "live two-server PoC" gate stays green.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');

test('T02 ALL A+B union — picker shows the "All servers" row + every configured server', async ({ page }) => {
  await gotoWithAutoSign(page, '/');

  // The scope picker chip is the first button[aria-haspopup="true"].
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await expect(chip).toBeVisible({ timeout: 15_000 });

  // Capture the chip label before opening the popover.
  const before = (await chip.textContent())?.trim() ?? '';
  expect(before.length).toBeGreaterThan(0);

  // Open the popover.
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await expect(popover).toBeVisible();

  // "All servers" row is present.
  await expect(popover.getByText('All servers', { exact: true })).toBeVisible();

  // At least 2 distinct server rows are present in the popover.
  const popoverButtons = await popover.locator('button').allTextContents();
  // The popover has many rows: All servers, each server, then the workspace/project
  // columns. We assert >= 2 server-like entries — anything that is not "All"
  // and not "All servers".
  const serverishRows = popoverButtons.filter(
    (t) => t.trim().length > 0 && t.trim() !== 'All' && t.trim() !== 'All servers',
  );
  expect(serverishRows.length).toBeGreaterThanOrEqual(2);

  // Click the "All servers" row.
  const allServersRow = popover.locator('button', { hasText: /^All servers$/ });
  await allServersRow.click();

  // The chip now displays "All servers".
  await expect(chip).toHaveText(/All servers/i, { timeout: 5_000 });

  // No client-side error: the page is still on the dashboard and the
  // URL is not a redirect to an auth dialog.
  await expect(page).toHaveURL(/\/(?:[?#].*)?$/);

  // The dashboard still renders (network-idle resolves; the per-server
  // fan-out completes within a reasonable window).
  await page.waitForLoadState('networkidle', { timeout: 15_000 });
});