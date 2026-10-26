/**
 * TASK-113 / T06 — A peer is offline during the list; A/B still render;
 * D shows as "Offline" chip; no global failure.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T06 offline peer — A/B render, the offline peer shows as Offline', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 3, offlineIndex: 2 });
  await gotoWithAutoSign(page, '/');

  // Switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();

  // The two online peers' hosts render.
  await expect(page.getByText('e2e-a', { exact: false })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('e2e-b', { exact: false })).toBeVisible();

  // The offline peer is still in the picker (it was discovered once) and
  // shows the "Offline" chip in its row.
  await chip.click();
  const popover2 = page.locator('.MuiPopover-paper').first();
  await expect(popover2.getByText('Offline', { exact: false })).toBeVisible();
  // The row for the offline peer is the disabled one — assert by visible
  // "Offline" text adjacent to the server's name.
  await expect(
    popover2.locator('button', { hasText: new RegExp(`${servers[2].server_name}.*Offline`, 's') }),
  ).toBeVisible();
});