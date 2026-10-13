// Video 22 scout ("What's new"): screenshots of the restyled pages, read-only. Usage: node whatsnew_scout.js
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw22'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const PAGES = ['/', '/test-prompt', '/builder/quick-test', '/builder/virtual-scripts', '/test-plan/coverage', '/test-results/reports', '/run/tests', '/monitoring/heatmap', '/configuration/interface'];
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); const page = await ctx.newPage();
  for (const p of PAGES) {
    try {
      await page.goto(url(p), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(7000);
      const name = p.replace(/\W+/g, '_').replace(/^_|_$/g, '') || 'dashboard';
      await page.screenshot({ path: path.join(OUT, `scout-${name}.png`) }); console.log('ok', p);
    } catch (e) { console.log('ERR', p, redact(e.message).slice(0, 200)); }
  }
  await browser.close();
})();
