/**
 * TASK-179 P4 / T20 — Atlas follows the server picker.
 *
 * Replaces TASK-113's T20 ("Atlas stays single-server"), which the product decision of 2026-10-26 reversed:
 * with "All servers" picked, Atlas asks every server with the user's own login; with one server picked, it
 * asks that server only. The browser says so in each `send_message`:
 *   - `server_scope`: 'all' or the picked server's name;
 *   - `turn_auth`: the user's current login for that one turn.
 *
 * Skipped until the /agent socket can be mocked here; the unit tests (tests/frontend/allServer/turnScope.test.ts,
 * tests/backend_server/test_atlas_all_servers.py) cover the contract and G5-G8 are checked live on node1.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T20 Atlas scope — send_message carries server_scope all and the turn login in All mode', async ({ page }) => {
  await mockServer(page, { count: 2 });
  await gotoWithAutoSign(page, '/');

  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  await page.locator('.MuiPopover-paper').first().locator('button', { hasText: /^All servers$/ }).click();
  await expect(chip).toHaveText(/All servers/i);

  await gotoWithAutoSign(page, '/atlas');
  await page.waitForLoadState('networkidle', { timeout: 10_000 });

  const sent = await page.evaluate(() => new Promise((resolve) => {
    const socket = window.__vptSocket;
    const original = socket.emit.bind(socket);
    socket.emit = (event, payload, ...rest) => {
      if (event === 'send_message') resolve(payload);
      return original(event, payload, ...rest);
    };
    const box = document.querySelector('textarea, input[type="text"]');
    box.focus();
  }));
  await page.keyboard.type('how many devices on the platform');
  await page.keyboard.press('Enter');

  const payload = await sent;
  expect(payload.server_scope).toBe('all');
  expect(payload.turn_auth).toBeTruthy();
});
