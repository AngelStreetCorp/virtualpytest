// TASK-75 device page layouts on /device-control — fully mocked, no device needed.
// Every /server/* call is answered here, so the spec runs the same locally and on a deployed bundle.
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('./_navigate');

const DEVICE_COUNT = 10;
const HOSTS = [
  {
    host_name: 'e2e-lay',
    host_url: 'https://e2e.invalid/host/e2e-lay',
    host_port: 6109,
    status: 'online',
    devices: Array.from({ length: DEVICE_COUNT }, (_, i) => ({
      device_id: `device${i + 1}`,
      device_name: `Box ${String(i + 1).padStart(2, '0')}`,
      device_model: 'stb',
      device_capabilities: { av: 'hdmi_stream', remote: 'ir_remote' },
      remote_profiles: ['ir:stb'],
      ir_type: 'stb',
      video_stream_path: `/host/stream/capture${i + 1}`,
      video_capture_path: `/var/www/html/stream/capture${i + 1}`,
    })),
  },
];

const LAYOUTS = [
  ['Side by side', 2],
  ['Stacked', 2],
  ['3 in a row', 3],
  ['Grid 2×2', 4],
  ['Grid 3×2', 6],
  ['Grid 4×2', 8],
  ['Focus + below', 4],
  ['Focus + right', 4],
  ['One full', 1],
];

async function mockServer(page) {
  await page.route(/\/server\//, (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/server/system/getAllHosts')) return route.fulfill({ json: { success: true, hosts: HOSTS } });
    return route.fulfill({ json: { success: true } });
  });
}

async function openPage(page) {
  await mockServer(page);
  await gotoWithAutoSign(page, '/device-control');
  await expect(page.getByText('Box 01 - e2e-lay')).toBeVisible();
}

async function pickView(page, name) {
  await page.getByRole('button', { name: 'View', exact: true }).click();
  await page.getByRole('menuitemradio', { name }).click();
}

const slots = (page) => page.locator('[data-slot]');
const slotName = (page, i) => slots(page).nth(i).locator('text=/Box \\d\\d/').first();

test.describe('Device page layouts (TASK-75)', () => {
  test('View menu replaces Per page and keeps the grid sizes', async ({ page }) => {
    await openPage(page);
    await expect(page.getByLabel('Devices per page')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'View', exact: true })).toContainText('24 per page');
    await pickView(page, '12 per page');
    await expect(page.getByRole('button', { name: 'View', exact: true })).toContainText('12 per page');
    await expect(page.getByText(/Box \d\d - e2e-lay/)).toHaveCount(DEVICE_COUNT);
  });

  for (const [name, count] of LAYOUTS) {
    test(`${name} shows ${count} slot(s) inside the window`, async ({ page }) => {
      await openPage(page);
      await pickView(page, name);
      await expect(slots(page)).toHaveCount(count);
      const last = await slots(page).nth(count - 1).boundingBox();
      expect(last.y + last.height).toBeLessThanOrEqual(page.viewportSize().height);
      // More devices than slots → pages by slot count.
      await expect(page.getByText(new RegExp(`^1–${count} / ${DEVICE_COUNT} · `))).toBeVisible();
    });
  }

  test('clicking a thumbnail promotes it, and the choice survives a reload', async ({ page }) => {
    await openPage(page);
    await pickView(page, 'Focus + right');
    await expect(slotName(page, 0)).toHaveText(/Box 01/);
    await expect(page.getByText(/1 live \+ 3 snapshots/)).toBeVisible();

    await slots(page).nth(2).click();
    await expect(slotName(page, 0)).toHaveText(/Box 03/);
    await expect(slotName(page, 2)).toHaveText(/Box 01/);

    await page.reload();
    await expect(page.getByRole('button', { name: 'View', exact: true })).toContainText('Focus + right');
    await expect(slotName(page, 0)).toHaveText(/Box 03/);
  });

  test('keys 1–9 switch layouts; Reset order restores the filter order', async ({ page }) => {
    await openPage(page);
    await page.keyboard.press('4');
    await expect(slots(page)).toHaveCount(4);
    await page.keyboard.press('8');
    await slots(page).nth(1).click();
    await expect(slotName(page, 0)).toHaveText(/Box 02/);
    await page.getByRole('button', { name: 'View', exact: true }).click();
    await page.getByRole('button', { name: 'Reset order' }).click();
    await expect(slotName(page, 0)).toHaveText(/Box 01/);
  });
});
