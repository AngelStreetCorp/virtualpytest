// Video 22 add-on scout: /monitoring/analytics, its tabs. Read-only.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const path = require('path'); const OUT = path.join(__dirname, 'raw22');
const { VIEW_CSS, DPR, url, CURSOR, redact } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); const page = await ctx.newPage();
  try {
    await page.goto(url('/monitoring/analytics'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(9000);
    await page.screenshot({ path: path.join(OUT, 'scout-an-0.png') });
    const tabs = page.getByRole('tab'); const n = await tabs.count(); const names = [];
    for (let i = 0; i < n; i++) names.push((await tabs.nth(i).innerText()).trim());
    console.log('tabs:', JSON.stringify(names));
    for (let i = 0; i < n; i++) {
      await tabs.nth(i).click(); await page.waitForTimeout(7000);
      await page.screenshot({ path: path.join(OUT, `scout-an-${i + 1}.png`) });
      const t = (await page.locator('main, body').first().innerText()).replace(/\s+/g, ' ');
      console.log(i + 1, names[i], '| err:', /error|failed|no data/i.test(t), '| labox:', /labox/i.test(t), '|', t.slice(0, 160));
    }
  } catch (e) { console.log('ERR', redact(e.message).slice(0, 300)); }
  await browser.close();
})();
