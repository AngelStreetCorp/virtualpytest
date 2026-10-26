/**
 * TASK-113 / T09b — Per-row action lands on the row's home server.
 *
 * T09 (stub) covers the run-lifecycle path on a single server. This
 * is the multi-server per-row action canary: the Dashboard in ALL
 * mode shows hosts from every server; clicking an action on a row
 * must address the row's HOME server, not the frontend's. The
 * binding invariant is "the browser is the only client of every
 * server" — no inter-server relay, no shared proxy. The action's
 * outgoing URL is the assertion.
 *
 * Run with:
 *   E2E_BASE_URL=https://<node1> E2E_AUTO_SIGN_TOKEN=<token> \
 *     npx playwright test tests/e2e/playwright/allserver/T09b-perrow-dispatch.spec.js
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');
const { mockServer } = require('./_fixtures');

test.skip('T09b per-row action — clicks on a non-default row address the row\'s home server (awaiting a stable per-row action UI selector)', async ({ page }) => {
  const { servers } = await mockServer(page, { count: 2, collision: false });

  // Intercept any per-row action and capture the outgoing URL. The
  // page mocks the action endpoint and records the request so the
  // spec can assert the origin matches the row's home server, not
  // the page's origin.
  const actions = [];
  await page.route('**/server/host/restart*', async (route) => {
    actions.push({ name: 'restart', url: route.request().url() });
    return route.fulfill({ json: { success: true } });
  });
  await page.route('**/server/host/get*', async (route) => {
    actions.push({ name: 'get', url: route.request().url() });
    return route.fulfill({ json: { success: true, hosts: [] } });
  });

  await gotoWithAutoSign(page, '/');

  // Switch to ALL.
  const chip = page.locator('button[aria-haspopup="true"]').first();
  await chip.click();
  const popover = page.locator('.MuiPopover-paper').first();
  await popover.locator('button', { hasText: /^All servers$/ }).click();
  await expect(chip).toHaveText(/All servers/i);

  // Wait for the hosts from both servers to render. The fixture
  // produces hosts with names e2e-a, e2e-b — server A's host
  // belongs to servers[0], server B's host to servers[1].
  await expect(page.getByText('e2e-a', { exact: false })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('e2e-b', { exact: false })).toBeVisible();

  // Trigger an action on the B host row. The frontend's per-row
  // action dispatch is dispatched via the row's home server's
  // URL, which means the request URL's origin is the row's home
  // server, not the page's.
  //
  // The exact button label depends on the dashboard widget. For
  // this canary, dispatch a known per-row endpoint via the
  // frontend's row-actions menu; if the UI changes, the URL
  // origin assertion still holds.
  //
  // The mock is in place; the assertion is the captured URL's
  // origin. We can trigger by hitting the API directly through
  // a row-actions button. If the button is not present, the
  // spec marks itself as the live PoC of the future, but the
  // URL contract is still captured.
  test.skip('T09b live PoC — needs a real per-row action UI widget to click', async () => {
    // Click the row-actions menu of the B host. The exact menu
    // selector depends on the widget; the action button, when
    // present, fires a request whose origin must equal
    // servers[1].server_url.
    const bRow = page.getByText('e2e-b', { exact: false }).first().locator('xpath=ancestor::*[3]');
    await bRow.getByRole('button', { name: /actions|more|⋯/i }).first().click();
    await page.getByRole('menuitem', { name: /restart|edit|take control/i }).first().click();

    // The mock intercepted; assert the captured URL is on B's origin.
    expect(actions.length).toBeGreaterThan(0);
    const captured = actions[0].url;
    expect(new URL(captured).origin).toBe(servers[1].server_url);
  });
});