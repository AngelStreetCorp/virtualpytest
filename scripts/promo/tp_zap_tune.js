// Off-camera helper for tp_zap_capture.js: take control of stb3 (vpt-pi1) from the Device page, press the given
// keys (default none), screenshot the page after each, release. Usage: node tp_zap_tune.js [KEY ...]
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw17'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, BASE, url, CURSOR, relay, api } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const CARD = 'stb3 - vpt-pi1'; const keys = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(([origin, labels]) => { if (location.origin !== origin) return; localStorage.setItem('rec_filters_target', JSON.stringify(labels)); localStorage.setItem('rec_filters_model', '[]'); localStorage.setItem('rec_filters_flag', '[]'); }, [new URL(BASE).origin, [CARD]]);
  await relay(ctx); const page = await ctx.newPage();
  try {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2000);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 });
    const title = page.locator(`text=/^${CARD}$/`).first(); await title.waitFor({ timeout: 90000 });
    for (let i = 0; i < 4 && !/Device \(1\)/.test(await page.locator('body').innerText()); i++) { await page.reload({ waitUntil: 'load' }); await title.waitFor({ timeout: 90000 }); await page.waitForTimeout(3000); }
    await page.waitForTimeout(12000);
    const clip = async name => { await page.screenshot({ path: path.join(OUT, `${name}.png`), clip: { x: 215, y: 125, width: 290, height: 190 } }); };
    await clip('tune-0'); let n = 0;
    for (const k of keys) {
      const r = await api('POST', '/server/remote/executeCommand', { host_name: 'vpt-pi1', device_id: 'device3', command: 'press_key', params: { key: k } }); console.log('pressed', k, r.success);
      n++; await page.waitForTimeout(5000); await clip(`tune-${n}a`); await page.waitForTimeout(1000); await clip(`tune-${n}b`);
    }
  } catch (e) { console.log('ERROR', e.message.slice(0, 200)); await page.screenshot({ path: path.join(OUT, 'tune-error.png') }).catch(() => {}); }
  const l = await api('GET', '/server/control/lockedDevices'); const lock = ((l.locked_devices || {})['vpt-pi1:device3']);
  if (lock) console.log('released', (await api('POST', '/server/control/releaseControl', { host_name: 'vpt-pi1', device_id: 'device3', session_id: lock.owner_session_id })).success);
  await browser.close();
})();
