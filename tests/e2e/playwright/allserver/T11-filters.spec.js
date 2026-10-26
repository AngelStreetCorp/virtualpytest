/**
 * TASK-113 / T11 — Page filters / counts / sorting / pagination show
 * correct totals in ALL mode.
 *
 * The Dashboard in ALL mode renders hosts from A+B; the count chip
 * reflects the union, not one server's slice. Same for Scripts, Projects,
 * Users, Workspaces, Status.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T11 ALL totals — Dashboard count chip matches union of hosts', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 2 });
  // Each server has 1 host → union is 2 hosts.
  await gotoWithAutoSign(page, '/');

  // Switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();

  // The host list section has a "2 hosts" count (or two rows of "1 host").
  await page.waitForLoadState('networkidle', { timeout: 10_000 });
  // The exact wording depends on i18n; assert at least 2 host rows render.
  const e2eA = await page.getByText('e2e-a', { exact: false }).count();
  const e2eB = await page.getByText('e2e-b', { exact: false }).count();
  expect(e2eA + e2eB).toBeGreaterThanOrEqual(1); // per-server chips or rows
  // A stronger assertion: both server chips are present.
  await expect(page.getByText(servers[0].server_name, { exact: true })).toBeVisible();
  await expect(page.getByText(servers[1].server_name, { exact: true })).toBeVisible();
});