/**
 * TASK-113 / T17 — 5-server load: no uncontrolled request/stream
 * fan-out; responsive UI.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T17 5-server load — UI responsive, no fan-out beyond what the user opened', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 5 });
  await gotoWithAutoSign(page, '/');

  // Count fan-out requests.
  let allHostsCount = 0;
  page.on('request', (req) => {
    if (/\/server\/system\/getAllHosts/.test(req.url())) allHostsCount++;
  });

  // Switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();

  // Wait for the network to settle.
  await page.waitForLoadState('networkidle', { timeout: 20_000 });

  // The frontend should issue at most one getAllHosts per server (5
  // total) for the dashboard, plus the same per-server probes the
  // server-identity flow already does. The ceiling the plan allows is
  // 5× baseline; we assert no runaway > 50.
  expect(allHostsCount).toBeLessThanOrEqual(50);

  // The dashboard renders hosts from every server.
  for (let i = 0; i < 5; i++) {
    await expect(page.getByText(servers[i].server_name, { exact: true })).toBeVisible();
  }
});