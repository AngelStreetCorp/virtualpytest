// Video 24 scout (read-only unless DRIVE=1): Device page on RPI1-server, tiles of vpt-pi3 (FireTv, switch1), open one tile,
// optionally Take Control and screenshot the remote panel. Usage: PROMO_BASE=https://virtualpytest.angelstreet.io DEV=FireTv [DRIVE=1] node scout24_devices.js
// Only run DRIVE=1 under a vpt-lease on the device.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw24'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const DEV = process.env.DEV || 'FireTv', HOST = 'vpt-pi3', SERVER = 'RPI1-server', DRIVE = process.env.DRIVE === '1';
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); const page = await ctx.newPage();
  const log = s => console.log(redact(s)); const shot = n => page.screenshot({ path: path.join(OUT, `scout-${n}.png`) });
  try {
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(5000);
    const sel = page.locator('.MuiFormControl-root:has(label:has-text("Server")) .MuiSelect-select').first();
    await sel.waitFor({ timeout: 30000 });
    if ((await sel.innerText()).trim() !== SERVER) { await sel.click(); await page.waitForTimeout(800);
      await page.locator('[role="option"]').filter({ hasText: new RegExp(`^${SERVER}`) }).first().click(); await page.waitForTimeout(9000); }
    log('server: ' + (await sel.innerText()).trim());
    const t = page.locator(`text=/${DEV} - ${HOST}$/`).first();   // 36 tiles, 24 per page: the tile may be on page 2
    if (!(await t.waitFor({ timeout: 20000 }).then(() => true).catch(() => false))) {
      await page.getByRole('button', { name: 'Go to next page' }).click(); await page.waitForTimeout(3000); }
    await t.waitFor({ timeout: 60000 });
    await page.waitForTimeout(25000); await shot(`${DEV}-grid`);
    const tile = page.locator(`text=/^${DEV} - ${HOST}$/`).first(); const b = await tile.boundingBox();
    await page.mouse.move(b.x + 60, b.y + b.height + 100, { steps: 15 }); await page.waitForTimeout(2000); await shot(`${DEV}-hover`);
    await page.mouse.click(b.x + 60, b.y + b.height + 100); await page.waitForTimeout(8000); await shot(`${DEV}-open`);
    if (DRIVE) {
      const take = page.getByRole('button', { name: /take control/i }).first();
      if (await take.count()) { await take.click(); await page.waitForTimeout(12000); await shot(`${DEV}-control`); }
      else log('no Take Control button');
      log('buttons: ' + (await page.locator('button').evaluateAll(bs => bs.map(x => (x.getAttribute('aria-label') || x.innerText || '').trim()).filter(Boolean))).slice(0, 80).join(' | '));
    }
  } catch (e) { log('ERROR ' + e.message.slice(0, 300)); await shot('error').catch(() => {}); }
  await ctx.close(); await browser.close();
})();
