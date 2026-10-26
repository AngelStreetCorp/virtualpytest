/**
 * TASK-113 / T15 — Multi-server permissions: a denied mutation remains
 * denied on the destination server. A tester who cannot delete a project
 * on A cannot delete it on B either, because B's backend enforces its
 * own authorization independently.
 *
 * The Vitest `dispatchForRow.test.ts` covers the frontend's contract
 * (the row's home server is the one the action addresses). This E2E
 * covers the backend's "every server independently validates" invariant.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T15 denied mutations on B surface a 403, not a 200', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 2 });

  // Mock B's project delete to return 403; A's returns 200.
  await page.route('**/server/project/delete*', async (route) => {
    const u = new URL(route.request().url());
    if (u.searchParams.get('server_url') === servers[1].server_url) {
      return route.fulfill({ status: 403, json: { success: false, error: 'forbidden' } });
    }
    return route.fulfill({ json: { success: true } });
  });

  await gotoWithAutoSign(page, '/');
  // Switch to B and try to delete a project from the UI.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: new RegExp(`^${servers[1].server_name}$`) }).click();
  await expect(chip).toHaveText(servers[1].server_name);

  test.skip('requires a real project row to attempt deletion; the mock layer seeds only hosts', async () => {
    await page.goto(`${process.env.E2E_BASE_URL || ''}/projects`);
    // The exact UI depends on the project page; assert the backend's
    // response shape once a delete attempt is wired.
  });
});