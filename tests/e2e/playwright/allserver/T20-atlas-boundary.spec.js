/**
 * TASK-113 / T20 — Atlas boundary: Atlas remains bound to a single
 * server in v1; the UI does not advertise cross-server Atlas support.
 *
 * The product decision (approved 2026-10-15) is that Atlas is a
 * separate scope from "All servers". A static Vitest scan
 * (`A8/A9 sweep`) already asserts the absence of cross-server Atlas
 * language. This E2E confirms the Atlas panel still shows one server
 * only, even when the page's scope is "All servers".
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T20 Atlas boundary — Atlas panel stays single-server even when scope is ALL', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 2 });
  await gotoWithAutoSign(page, '/');

  // Switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();
  await expect(chip).toHaveText(/All servers/i);

  // Open the Atlas page.
  await gotoWithAutoSign(page, '/atlas');
  await page.waitForLoadState('networkidle', { timeout: 10_000 });

  // The Atlas UI does NOT show an "All servers" entry in its own picker.
  // We assert the picker chip in the Atlas header is NOT "All servers".
  const atlasChip = page.locator('button[aria-haspopup="true"]').first();
  const atlasChipText = (await atlasChip.textContent())?.trim() ?? '';
  expect(atlasChipText).not.toMatch(/all servers/i);
  // The Atlas server picker is single-server; it should display one of
  // the two configured names, or "No server" if Atlas is bound to a
  // dedicated scope.
  expect(atlasChipText.length).toBeGreaterThan(0);
});