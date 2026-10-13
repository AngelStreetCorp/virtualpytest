// TASK-76 group remote control on /device-control — fully mocked, no device needed.
// Every /server/* call is answered here, so the spec runs the same on a local dev server
// and on a deployed bundle: the hosts, locks and group sends below are fakes.
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('./_navigate');

const device = (id, name, model, remote, profiles) => ({
  device_id: id,
  device_name: name,
  device_model: model,
  device_capabilities: { av: 'hdmi_stream', remote },
  remote_profiles: profiles,
  ir_type: profiles.find((p) => p.startsWith('ir:'))?.slice(3),
  video_stream_path: `/host/stream/capture${id.slice(-1)}`,
  video_capture_path: `/var/www/html/stream/capture${id.slice(-1)}`,
});

const host = (name, devices) => ({
  host_name: name,
  host_url: `https://e2e.invalid/host/${name}`,
  host_port: 6109,
  status: 'online',
  devices,
});

// Two IR stbs + one BLE stb (must never group with them), and a Fire OS pair on ADB + IR.
const HOSTS = [
  host('e2e-pi1', [
    device('device1', 'Stb IR A', 'stb', 'ir_remote', ['ir:stb']),
    device('device2', 'Stb BLE', 'stb', 'bluetooth_remote', ['ble:arris']),
  ]),
  host('e2e-pi2', [
    device('device1', 'Stb IR B', 'stb', 'ir_remote', ['ir:stb']),
    device('device2', 'Fire A', 'fire_tv_fireos', ['android_tv', 'ir_remote'], ['adb_tv', 'ir:fire_tv']),
  ]),
  host('e2e-pi3', [
    device('device1', 'Stb IR C', 'stb', 'ir_remote', ['ir:stb']),
    device('device2', 'Fire B', 'fire_tv_fireos', ['android_tv', 'ir_remote'], ['adb_tv', 'ir:fire_tv']),
  ]),
];

async function mockServer(page, { lockedBy = {}, failing = {} } = {}) {
  const calls = { take: [], release: [], group: [], single: [] };
  await page.route(/\/server\//, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const body = req.postDataJSON?.() ?? null;
    if (path.endsWith('/server/system/getAllHosts')) return route.fulfill({ json: { success: true, hosts: HOSTS } });
    if (path.endsWith('/server/control/takeControl')) {
      calls.take.push(body);
      const owner = lockedBy[`${body.host_name}/${body.device_id}`];
      if (owner) {
        return route.fulfill({ status: 409, json: { success: false, errorType: 'device_locked', owner_user_name: owner } });
      }
      return route.fulfill({ json: { success: true } });
    }
    if (path.endsWith('/server/control/releaseControl')) {
      calls.release.push(body);
      return route.fulfill({ json: { success: true } });
    }
    if (path.endsWith('/server/remote/executeCommandGroup')) {
      calls.group.push(body);
      const results = body.targets.map((t) => {
        const error = failing[`${t.host_name}/${t.device_id}`] ?? null;
        return { ...t, success: !error, error, ms: 40, response: { success: !error } };
      });
      return route.fulfill({ json: { success: results.every((r) => r.success), results, skew_ms: 7 } });
    }
    if (path.endsWith('/server/remote/executeCommand')) {
      calls.single.push(body);
      return route.fulfill({ json: { success: true, status: { healthy: true, device_present: true, tx_probe_ok: true } } });
    }
    return route.fulfill({ json: { success: true } });
  });
  return calls;
}

// IR remote keys are image hotspots titled "<label> - <comment>".
const remoteKey = (page, label) => page.locator(`[title^="${label} - "]`).first();

const tile = (page, name) => page.locator('[data-device-tile]').filter({ hasText: name });

async function enterGroupMode(page) {
  await gotoWithAutoSign(page, '/device-control');
  await expect(tile(page, 'Stb IR A')).toBeVisible();
  await page.getByRole('button', { name: 'Group control' }).click();
}

async function pick(page, name) {
  await tile(page, name).getByRole('checkbox').click();
}

test.describe('Group remote control (TASK-76)', () => {
  test('an IR stb and a BLE stb never group; other models dim', async ({ page }) => {
    await mockServer(page);
    await enterGroupMode(page);
    await pick(page, 'Stb IR A');

    await expect(tile(page, 'Stb BLE')).toHaveCSS('opacity', '0.35');
    await expect(tile(page, 'Fire A')).toHaveCSS('opacity', '0.35');
    await expect(tile(page, 'Stb IR B')).toHaveCSS('opacity', '1');
    await expect(page.getByText('IR stb', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Control 1 together/ })).toBeDisabled();

    await pick(page, 'Stb IR B');
    await expect(page.getByRole('button', { name: 'Control 2 together' })).toBeEnabled();
  });

  test('a two-remote device offers a remote picker, ADB first', async ({ page }) => {
    await mockServer(page);
    await enterGroupMode(page);
    await pick(page, 'Fire A');

    const picker = page.getByRole('combobox', { name: 'Group remote' });
    await expect(picker).toHaveText('ADB');
    await picker.click();
    await page.getByRole('option', { name: 'IR fire_tv' }).click();
    await expect(picker).toHaveText('IR fire_tv');
    await expect(tile(page, 'Fire B')).toHaveCSS('opacity', '1');
  });

  test('one key goes to every included device in one group request', async ({ page }) => {
    const calls = await mockServer(page, {
      lockedBy: { 'e2e-pi3/device1': 'marie' },
      failing: { 'e2e-pi2/device1': 'IR timeout' },
    });
    await enterGroupMode(page);
    for (const name of ['Stb IR A', 'Stb IR B', 'Stb IR C']) await pick(page, name);
    await page.getByRole('button', { name: 'Control 3 together' }).click();

    await expect(page.getByText('2/3 controlled')).toBeVisible();
    await expect(page.getByText(/Stb IR C: .*marie/)).toBeVisible();

    await remoteKey(page, 'OK').click();
    await expect.poll(() => calls.group.length).toBe(1);
    const sent = calls.group[0];
    expect(sent.remote_profile).toBe('ir:stb');
    expect(sent.command).toBe('press_key');
    expect(sent.device_model).toBe('stb');
    expect(sent.targets).toEqual([
      { host_name: 'e2e-pi1', device_id: 'device1' },
      { host_name: 'e2e-pi2', device_id: 'device1' },
    ]);
    await expect(page.getByText('Sent', { exact: true })).toHaveCount(1);
    await expect(page.getByText('Error', { exact: true })).toHaveCount(1);

    // Exclude one device: the next key only goes to the other.
    await page.getByRole('checkbox', { name: 'Included' }).nth(1).uncheck();
    await remoteKey(page, 'OK').click();
    await expect.poll(() => calls.group.length).toBe(2);
    expect(calls.group[1].targets).toEqual([{ host_name: 'e2e-pi1', device_id: 'device1' }]);

    await page.getByRole('button', { name: 'Release all' }).click();
    await expect(page.getByText('2/3 controlled')).toBeHidden();
    expect(calls.release.map((r) => `${r.host_name}/${r.device_id}`).sort()).toEqual([
      'e2e-pi1/device1',
      'e2e-pi2/device1',
    ]);
  });
});
