// Video 22 scout 2: Settings menu (theme/language), the goto report and its header buttons, the share dialog. Read-only.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw22');
const { VIEW_CSS, DPR, url, CURSOR, redact } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const RID = process.env.RID || 'aaa82683-8bbf-4ed7-b636-3443233ad435';
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); const page = await ctx.newPage();
  const shot = n => page.screenshot({ path: path.join(OUT, `scout2-${n}.png`) });
  try {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(6000);
    await page.getByRole('button', { name: /^settings$/i }).first().click(); await page.waitForTimeout(1500); await shot('settings-menu');
    console.log('menu:', (await page.locator('[role="menu"]').first().innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 400));
    await page.keyboard.press('Escape');
    // the share deep link for this run
    await page.goto(url(`/test-results/reports?share=${RID}`), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(7000); await shot('share-dialog');
    console.log('dialog:', (await page.locator('[role="dialog"]').first().innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 600));
    await page.keyboard.press('Escape'); await page.waitForTimeout(800);
    // the report: open it from its row
    const row = page.locator('tr').filter({ hasText: /\bgoto\b/i }).first();
    console.log('row:', (await row.innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 200));
    const btns = row.locator('button, a'); console.log('row buttons', await btns.count());
    for (let i = 0; i < await btns.count(); i++) console.log(' ', i, await btns.nth(i).getAttribute('aria-label'), await btns.nth(i).getAttribute('title'));
    await shot('reports');
  } catch (e) { console.log('ERR', redact(e.message).slice(0, 300)); await shot('error'); }
  await browser.close();
})();
