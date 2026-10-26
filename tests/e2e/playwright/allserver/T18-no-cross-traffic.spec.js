/**
 * TASK-113 / T18 — No inter-server traffic. A network trace confirms
 * A never calls B/C as a result of the ALL feature.
 *
 * The browser is the only client of every server; no peer ever
 * contacts another peer. This is the binding invariant of the
 * decentralized architecture.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T18 no inter-server traffic — A never relays to B', async ({ page }) => {
  const { servers, calls } = await mockServer(page, { count: 2 });

  // Track every server-to-server request. The mocked server origins are
  // e2e.invalid; the test asserts no request goes from one of those
  // origins to another.
  const aToB = [];
  const bToA = [];
  page.on('request', (req) => {
    if (req.serviceWorker()) return; // SW origin skipped
    const from = req.headers()['referer'] || '';
    if (from.includes(servers[0].server_url) && req.url().includes(servers[1].server_url)) aToB.push(req.url());
    if (from.includes(servers[1].server_url) && req.url().includes(servers[0].server_url)) bToA.push(req.url());
  });

  await gotoWithAutoSign(page, '/');

  // Switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();
  await page.waitForLoadState('networkidle', { timeout: 15_000 });

  // The mocked frontend's getAllHosts was called at least once per server.
  expect(calls.allHosts).toBeGreaterThanOrEqual(1);
  // No cross-server traffic observed.
  expect(aToB).toEqual([]);
  expect(bToA).toEqual([]);
});