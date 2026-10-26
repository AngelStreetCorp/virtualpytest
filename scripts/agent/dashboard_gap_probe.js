// Headless check of UI_STYLE 16: logs, for every dashboard card, the space above and below its content block
// (header + body), which must be equal within 2 px, plus the left / right padding.
//   TOKEN=$(scripts/agent/auto_sign_token.sh) BASE=https://virtualpytest.angelstreet.io node scripts/agent/dashboard_gap_probe.js
// Needs Playwright from tests/e2e/playwright/node_modules. Never prints the token.
const { chromium } = require(`${process.env.HOME}/virtualpytest/tests/e2e/playwright/node_modules/playwright`);
const { TOKEN, BASE = 'http://localhost:3000' } = process.env;
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1500, height: 900 } })).newPage();
  await page.goto(`${BASE}/?auto_signed=${encodeURIComponent(TOKEN)}`);
  await page.waitForTimeout(5000);
  let bad = 0;
  for (const name of ['Overview', 'Scripts', 'Devices', 'System']) {
    const tab = page.getByRole('tab', { name: new RegExp(name) }).first();
    if (!(await tab.count())) continue;
    await tab.click();
    await page.waitForTimeout(2000);
    const rows = await page.evaluate(() => [...document.querySelectorAll('[data-testid^="dash-card-"]')].map((card) => {
      const r = card.getBoundingClientRect();
      const leaves = [...card.querySelectorAll('*')].filter((e) => {
        const b = e.getBoundingClientRect();
        if (!b.width || !b.height || b.top < r.top || b.bottom > r.bottom + 0.5) return false;
        return e.tagName === 'svg' || e.hasAttribute('data-measure') || [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      });
      if (!leaves.length) return { id: card.dataset.testid, skipped: true };
      const rs = leaves.map((e) => e.getBoundingClientRect());
      const top = Math.min(...rs.map((b) => b.top)) - r.top - 1;
      const bottom = r.bottom - 1 - Math.max(...rs.map((b) => b.bottom));
      const cs = getComputedStyle(card);
      return { id: card.dataset.testid, top, bottom, padL: cs.paddingLeft, padR: cs.paddingRight };
    }));
    for (const row of rows) {
      if (row.skipped) { console.log(name, row.id, 'no content'); continue; }
      const ok = Math.abs(row.top - row.bottom) <= 2 && row.padL === row.padR;
      if (!ok) bad += 1;
      console.log(name, row.id, `top=${row.top.toFixed(1)} bottom=${row.bottom.toFixed(1)} pad=${row.padL}/${row.padR}`, ok ? 'ok' : 'UNEVEN');
    }
  }
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
