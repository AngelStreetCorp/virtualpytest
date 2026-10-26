/**
 * TASK-113 / T16 — Reload state: `localStorage` rehydrates the chosen
 * scope only where existing persistence supports it.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');

test('T16 reload — the scope persists across reloads when the user is still signed in', async ({ page }) => {
  await gotoWithAutoSign(page, '/');

  // Switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();
  await expect(chip).toHaveText(/All servers/i);

  // Reload — the chip should still show "All servers".
  await page.reload();
  await page.waitForLoadState('networkidle');
  await expect(page.locator('button[aria-haspopup="true"]').first()).toHaveText(/All servers/i);
});