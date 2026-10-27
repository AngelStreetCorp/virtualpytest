// Video 16: Atlas analytics on real data (TASK-43). The deployed site's AI agent page (no local Vite, no relay):
// each prompt typed, sent, and the answer awaited (a finished turn prints its duration "12.3s" in the stats footer).
// Usage: PROMO_BASE=https://virtualpytest.angelstreet.io node atlas_capture.js scout -> raw16/scout-*.png + scout.log
//        PROMO_BASE=https://virtualpytest.angelstreet.io node atlas_capture.js       -> raw16/atlas.mp4 + atlas.marks.json
// PROMPTS (|-separated) overrides the questions.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw16'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const PROMPTS = (process.env.PROMPTS || [
  'Compare pass rate by device',
  `Provide the last known KPI radar for userinterface ${process.env.ATLAS_UI}`,
  `Show only KPI regressions over 10% for ${process.env.ATLAS_UI} over the last 30 days`,
  `Build a canvas for stb3 and stb4 with 3 panels: pass rate, KPI averages for ${process.env.ATLAS_UI}, and incidents over the last 7 days`,
].join('|')).split('|');
const FOOTER = /\b\d+\.\ds\b/g;   // one per completed agent turn

async function walk(page, mark, shot, log) {
  await page.goto(url('/ai-agent'), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(6000);
  // the server whose hosts the answers cover (SERVER, default RPI1): its device names are neutral
  const want = new RegExp(process.env.SERVER || 'RPI1', 'i'); const sel = page.locator('.MuiSelect-select').first();
  if (!want.test(await sel.innerText())) {
    await sel.dispatchEvent('mousedown'); await page.waitForTimeout(800);
    await page.locator('[role="option"]').filter({ hasText: want }).first().click(); await page.waitForTimeout(6000);
    log(`server: ${await sel.innerText()}`);
  }
  mark('page'); await shot('page');
  for (const [i, prompt] of PROMPTS.entries()) {
    const input = page.locator('textarea[placeholder="How can I help you?"], textarea[placeholder="Message..."], input[placeholder="How can I help you?"], input[placeholder="Message..."]').first();
    await input.waitFor({ timeout: 30000 });
    const before = ((await page.locator('body').innerText()).match(FOOTER) || []).length;
    const b = await input.boundingBox(); await glide(page, b.x + 40, b.y + b.height / 2, 400);
    await input.pressSequentially(prompt, { delay: 35 }); await page.waitForTimeout(500);
    await page.keyboard.press('Enter'); mark(`ask-${i + 1}`); log(`asked ${i + 1}: ${prompt}`);
    let done = false;
    for (let s = 0; s < 120 && !done; s++) {
      await page.waitForTimeout(2000);
      const txt = await page.locator('body').innerText();
      if ((txt.match(FOOTER) || []).length > before) done = true;
      if (/AI service error|Something went wrong/i.test(txt.slice(-3000))) { log(`answer ${i + 1}: error text visible`); }
    }
    log(`answer ${i + 1}: ${done ? 'done' : 'not finished in 240 s'}`);
    await page.waitForTimeout(3000); await page.mouse.move(800, 500, { steps: 10 });
    mark(`answer-${i + 1}`); await shot(`answer-${i + 1}`);
    // let the viewer see the chart: scroll the answer into view and hold
    await page.mouse.wheel(0, 300); await page.waitForTimeout(2500); await shot(`answer-${i + 1}-scrolled`);
  }
  await page.waitForTimeout(1500); mark('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); const page = await ctx.newPage();
  const stop = scout ? null : await startRecorder(page, 'atlas');
  const marks = []; const t0 = Date.now(); const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  const logf = path.join(OUT, `${scout ? 'scout' : 'take'}.log`); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-${name}.png`) });
  try { await walk(page, mark, shot, log); }
  catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'atlas.marks.json'), JSON.stringify({ marks }, null, 1));
})();
