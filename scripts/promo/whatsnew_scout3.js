// Video 22 scout 3: open the goto report from its row, list the header buttons. Read-only.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const path = require('path'); const OUT = path.join(__dirname, 'raw22');
const { VIEW_CSS, DPR, url, CURSOR, redact } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); const page = await ctx.newPage();
  const shot = n => page.screenshot({ path: path.join(OUT, `scout3-${n}.png`) });
  try {
    await page.goto(url('/test-results/reports'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(7000);
    for (let i = 0; i < 3; i++) console.log('r', i, JSON.stringify((await page.locator('tbody tr').nth(i).innerText()).slice(0, 120)));
    const row = page.locator('tbody tr').filter({ hasText: /host - host-clone-1/ }).filter({ hasText: /goto/ }).first();
    console.log('row:', (await row.innerText()).replace(/\s+/g, ' ').slice(0, 160));
    const [pop] = await Promise.all([ctx.waitForEvent('page', { timeout: 20000 }), row.getByRole('button', { name: 'Open Report' }).first().click().then(() => console.log('clicked'))]);
    await pop.waitForLoadState('load'); const ru = pop.url(); await pop.close(); console.log('report host:', new URL(ru).host, new URL(ru).pathname.slice(0, 80));
    await page.goto(ru, { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(4000); await shot('report');
    const b = page.locator('button, a[role="button"], [role="button"]');
    for (let i = 0; i < Math.min(await b.count(), 25); i++) { const e = b.nth(i); console.log(' btn', i, JSON.stringify((await e.innerText().catch(() => '')).trim().slice(0, 30)), await e.getAttribute('title'), await e.getAttribute('aria-label')); }
    const fr = page.getByRole('button', { name: /^FR$/ }).first(); if (await fr.isVisible().catch(() => false)) { await fr.click(); await page.waitForTimeout(1500); await shot('report-fr'); }
  } catch (e) { console.log('ERR', redact(e.message).slice(0, 300)); await shot('error'); }
  await browser.close();
})();
