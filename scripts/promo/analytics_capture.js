// Video 22 add-on: the Analytics page (/monitoring/analytics), clicking through its tabs. Read-only.
// Usage: PROMO_BASE=https://virtualpytest.angelstreet.io node analytics_capture.js -> raw22/analytics.mp4 + marks
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path'); const OUT = path.join(__dirname, 'raw22');
const { VIEW_CSS, DPR, url, CURSOR, redact, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const TABS = ['Overview', 'Devices', 'KPI', 'Alerts', 'Project'];
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); const page = await ctx.newPage();
  const marks = []; let t0 = Date.now(), stop = null; const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  try {
    await page.goto(url('/monitoring/analytics'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(9000);
    stop = await startRecorder(page, 'analytics'); t0 = Date.now(); mark('page');
    await page.mouse.move(700, 500, { steps: 15 }); await page.waitForTimeout(2500);
    for (const name of TABS.slice(1)) {
      const tab = page.getByRole('tab', { name: new RegExp(`^${name}$`) }).first(); const b = await tab.boundingBox();
      await glide(page, b.x + b.width / 2, b.y + b.height / 2, 500); await page.mouse.move(800, 550, { steps: 15 });
      await page.waitForTimeout(3200); mark(name.toLowerCase()); await page.screenshot({ path: path.join(OUT, `take-an-${name}.png`) });
    }
    await page.waitForTimeout(800); mark('end');
  } catch (e) { console.log('ERROR', redact(e.message).slice(0, 300)); }
  if (stop) await stop();
  fs.writeFileSync(path.join(OUT, 'analytics.marks.json'), JSON.stringify({ marks }, null, 1));
  await browser.close(); console.log(marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
