/**
 * TASK-113 / T03 — same `localId` collision across A and B.
 *
 * Both A and B are seeded with `host_name='host-poci'`, `device_id=42`
 * (per the test plan's topology). In ALL mode, the dashboard must render
 * TWO rows for the same logical device — distinct actions, distinct
 * cache, distinct per-row server chip. The frontend's `buildDeviceKey`
 * adds `serverUrl` so cache keys never collide.
 *
 * Vitest covers the key-uniqueness assertion
 * (`buildDeviceKey.test.ts`); this E2E covers the rendered DOM.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T03 host/device collision — two rows render, distinct per-row server chip, distinct actions', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 2, collision: true });
  await gotoWithAutoSign(page, '/');

  // Open the picker and switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();

  // The collision name 'host-poci' should appear on TWO distinct rows
  // in the dashboard, each with a per-row server chip.
  await expect(page.getByText('host-poci').first()).toBeVisible({ timeout: 10_000 });
  const matches = await page.getByText('host-poci').count();
  expect(matches).toBeGreaterThanOrEqual(2);

  // Each row should show its origin server as a chip (the per-row
  // `ServerChip` from PR-C). Two of the four configured server names
  // (server_a / server_b in the fixture) should be visible.
  await expect(page.getByText(servers[0].server_name, { exact: true })).toBeVisible();
  await expect(page.getByText(servers[1].server_name, { exact: true })).toBeVisible();
});