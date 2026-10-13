// Closing shot for video 14: the interface the AI built, opened fresh in the navigation editor and fit to view.
// Read-only (no Take Control, no device). Usage: UI=google-tv-mobile-ai node tree_capture.js  -> raw14/tree.mp4 + tree.marks.json
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw14'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, relay, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const UI = process.env.UI || 'google-tv-mobile-ai';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await relay(ctx); const page = await ctx.newPage();
  const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  // load first, record once the tree is drawn (the editor needs a few seconds)
  await page.goto(url(`/navigation-editor/${UI}`), { waitUntil: 'load', timeout: 120000 });
  await page.getByText(/^watchlist$/i).first().waitFor({ timeout: 60000 }).catch(() => {});
  await page.mouse.move(800, 600); await page.waitForTimeout(4000);
  const stop = await startRecorder(page, 'tree'); const t1 = Date.now(); marks.length = 0;
  const m = l => marks.push({ label: l, t: (Date.now() - t1) / 1000 });
  m('loaded'); await page.waitForTimeout(1500);
  const fit = page.locator('button[title="fit view"]').first();
  if (await fit.isVisible().catch(() => false)) { const b = await fit.boundingBox(); await glide(page, b.x + b.width / 2, b.y + b.height / 2, 600); }
  await page.mouse.move(800, 640, { steps: 25 }); await page.waitForTimeout(5000); m('tree');
  await page.screenshot({ path: path.join(OUT, 'take-tree.png') });
  await page.waitForTimeout(1500); m('end');
  await stop(); await ctx.close(); await browser.close();
  fs.writeFileSync(path.join(OUT, 'tree.marks.json'), JSON.stringify({ marks }, null, 1));
  console.log('tree', marks.map(x => `${x.label}@${x.t.toFixed(1)}`).join(' '));
})();
