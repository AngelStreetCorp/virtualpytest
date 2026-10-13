// Headless dark + light screenshots of app routes against a running preview (TASK-56).
//
//   VPT_AUTO_SIGN=<token> node scripts/ui/ui_shots.cjs <spec.json> [dark,light]
//
// spec.json: [{ "name": "logs", "route": "/configuration/logs", "wait": 4000,
//               "steps": [ {"clickText": "Add Model", "shot": "add"}, {"press": "Escape"},
//                          {"click": "<css selector>", "wait": 1500, "shot": "menu"}, {"eval": "<js>"} ] }]
// Env: BASE (default http://localhost:3300), OUT (default ./ui-shots), AUDIT=1 (print ui_audit.js result
// per page), VIEWPORT=1500x900, PLAYWRIGHT (path of the playwright module; default: the e2e suite's).
// Every navigation carries ?auto_signed= (a plain reload lands on /login). Theme = localStorage 'theme-mode'.
// Never put Save / Delete / Run / Take Control in steps: the preview forwards to the LIVE server.
const fs = require('fs');
const path = require('path');
const repo = path.resolve(__dirname, '../..');
const pwPath = process.env.PLAYWRIGHT || [
  path.join(repo, 'tests/e2e/playwright/node_modules/playwright'),
  path.join(repo, 'tests/e2e/playwright/node_modules/@playwright/test'),
].find((p) => fs.existsSync(p));
if (!pwPath) { console.error('playwright not found: cd tests/e2e/playwright && npm ci, or set PLAYWRIGHT='); process.exit(2); }
const { chromium } = require(pwPath);
const TOKEN = process.env.VPT_AUTO_SIGN || '';
if (!TOKEN) { console.error('set VPT_AUTO_SIGN (AUTO_SIGN_TOKEN of the server .env; never commit it)'); process.exit(2); }
const BASE = process.env.BASE || 'http://localhost:3300';
const OUT = process.env.OUT || path.join(process.cwd(), 'ui-shots');
const [W, H] = (process.env.VIEWPORT || '1500x900').split('x').map(Number);
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const themes = (process.argv[3] || 'dark,light').split(',');
const audit = process.env.AUDIT ? fs.readFileSync(path.join(__dirname, 'ui_audit.js'), 'utf8') : null;
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch();
  for (const theme of themes) {
    const ctx = await browser.newContext({ viewport: { width: W, height: H } });
    await ctx.addInitScript((t) => { try { localStorage.setItem('theme-mode', t); localStorage.setItem('virtualpytest:language', 'en'); } catch (e) {} }, theme);
    const page = await ctx.newPage();
    const errs = new Set();
    page.on('pageerror', (e) => errs.add(String(e).slice(0, 200)));
    for (const s of spec) {
      const url = `${BASE}${s.route}${s.route.includes('?') ? '&' : '?'}auto_signed=${TOKEN}`;
      const file = (suffix) => path.join(OUT, `${s.name}${suffix ? '-' + suffix : ''}.${theme}.png`);
      try {
        await page.goto(url, { waitUntil: 'load', timeout: 45000 });
        await page.waitForTimeout(s.wait || 4000);
        await page.screenshot({ path: file('') });
        if (audit) {
          const a = await page.evaluate(audit);
          if (Object.keys(a).length) console.log('AUDIT', theme, s.name, JSON.stringify(a));
        }
        for (const st of s.steps || []) {
          try {
            if (st.click) await page.click(st.click, { timeout: 5000 });
            if (st.clickText) await page.getByText(st.clickText, { exact: !!st.exact }).first().click({ timeout: 5000 });
            if (st.press) await page.keyboard.press(st.press);
            if (st.eval) console.log(s.name, 'eval:', JSON.stringify(await page.evaluate(st.eval)));
            await page.waitForTimeout(st.wait || 900);
            if (st.shot) await page.screenshot({ path: file(st.shot) });
          } catch (e) { console.log('STEP-FAIL', theme, s.name, JSON.stringify(st), String(e).split('\n')[0]); }
        }
        console.log('ok', theme, s.name);
      } catch (e) { console.log('FAIL', theme, s.name, String(e).split('\n')[0]); }
    }
    if (errs.size) console.log(theme, 'pageerrors:', [...errs].slice(0, 5));
    await ctx.close();
  }
  await browser.close();
})();
