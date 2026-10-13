// Scout for the fingerprint video: Device page on the main server (Awesomation), the Localize button of
// host-clone-1's browser device (preferred userinterface sauce-demo). Screenshots only -> raw23/scout-*.png.
// Usage: PROMO_BASE=https://virtualpytest.angelstreet.io node localize_scout.js
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw23'); fs.mkdirSync(OUT, { recursive: true });
const { url, redact } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const P = process.env.P || '';
(async () => {
  const browser = await chromium.launch(); const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await ctx.newPage(); const log = s => console.log(redact(s));
  await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(12000);
  const server = page.locator('.MuiSelect-select').first();
  log('server select: ' + (await server.innerText().catch(() => '?')));
  await page.screenshot({ path: path.join(OUT, `scout-${P}1-page.png`) });
  const btns = page.locator('[aria-label="Localize current screen"]'); log('localize buttons: ' + await btns.count());
  if (!(await btns.count())) { await browser.close(); return; }
  await btns.first().scrollIntoViewIfNeeded(); await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, `scout-${P}2-button.png`) });
  await btns.first().click(); await page.waitForTimeout(12000);
  await page.screenshot({ path: path.join(OUT, `scout-${P}3-popover.png`) });
  log('popover: ' + (await page.locator('.MuiPopover-paper').innerText().catch(() => '?')).replace(/\n/g, ' | '));
  await browser.close();
})().catch(e => { console.error(redact(e.message)); process.exit(1); });
