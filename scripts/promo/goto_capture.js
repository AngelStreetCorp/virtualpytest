// Video 14, last beat: the map the AI built is used at once. Navigation editor on google-tv-mobile-ai, target S21x,
// Control, Auto Layout, then click a node -> Go To -> Run: the phone navigates there along the map. Repeated for each
// node in GOTO_NODES (default library,watchlist). Lease vpt-pi1/device1 first (deploy skill).
// Usage: node goto_capture.js scout -> raw14/scout-goto-*.png + scout-goto.log ; node goto_capture.js -> raw14/goto.mp4 + goto.marks.json
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw14'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, relay, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const UI = process.env.UI || 'google-tv-mobile-ai'; const TARGET = /S21x/;
const NODES = (process.env.GOTO_NODES || 'library,watchlist').split(',');

async function clickBox(page, loc, pause = 600) {
  await loc.waitFor({ timeout: 30000 }); const b = await loc.boundingBox(); await glide(page, b.x + b.width / 2, b.y + b.height / 2, pause);
}

async function walk(page, mark, shot, log) {
  await page.goto(url(`/navigation-editor/${UI}`), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(8000);
  mark('editor'); await shot('editor');
  // rpitest's tunnel drops now and then: an empty Target list means the page loaded while it was down, reload
  for (let attempt = 1; ; attempt++) {
    await clickBox(page, page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first(), 900);
    const opt = page.locator('[role="option"]').filter({ hasText: TARGET }).first();
    if (await opt.waitFor({ timeout: 10000 }).then(() => true).catch(() => false)) { await clickBox(page, opt, 1500); break; }
    if (attempt >= 3) throw new Error('S21x never offered in Target');
    log(`Target empty, reload (attempt ${attempt})`); await page.keyboard.press('Escape');
    await page.reload({ waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(9000);
  }
  mark('target');
  await clickBox(page, page.getByRole('button', { name: /^control$/i }).first()); mark('control');
  await page.waitForTimeout(18000); mark('stream'); await shot('control');
  // organize the map with the editor's own Auto Layout button
  await clickBox(page, page.locator('button[title="Auto Layout"]').first(), 900); await page.waitForTimeout(2500);
  mark('layout'); await shot('layout');
  for (const name of NODES) {
    const node = page.locator('.react-flow__node').filter({ hasText: new RegExp(`^\\s*${name}\\b`, 'i') }).first();
    await clickBox(page, node, 900); mark(`node-${name}`); await page.waitForTimeout(1200);
    await clickBox(page, page.getByRole('button', { name: /^go to$/i }).first(), 800); mark(`goto-${name}`); await page.waitForTimeout(1500);
    await shot(`gotopanel-${name}`);
    await clickBox(page, page.getByRole('button', { name: /^run$/i }).last(), 700); mark(`run-${name}`);
    // wait for the navigation to finish: the panel's Run button comes back (or a success/fail line), max 90 s
    let done = false;
    for (let i = 0; i < 45 && !done; i++) {
      await page.waitForTimeout(2000);
      const txt = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ');
      if (/navigation (completed|successful)|success|reached|arrived/i.test(txt) && await page.getByRole('button', { name: /^run$/i }).last().isEnabled().catch(() => false)) done = true;
      if (/fail|error/i.test(txt.slice(-4000)) && i > 3) log(`t+${(i + 1) * 2}s possible error text`);
    }
    log(`${name}: ${done ? 'done' : 'no end detected in 90 s'}`);
    await page.waitForTimeout(2500); mark(`at-${name}`); await shot(`at-${name}`);
    const close = page.getByRole('button', { name: /^close$/i }).last();
    if (await close.isVisible().catch(() => false)) { await clickBox(page, close, 500); await page.waitForTimeout(1200); }
  }
  await page.waitForTimeout(1500); mark('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await relay(ctx); const page = await ctx.newPage();
  const stop = scout ? null : await startRecorder(page, 'goto');
  const marks = []; const t0 = Date.now(); const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  const logf = path.join(OUT, `${scout ? 'scout' : 'take'}-goto.log`); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-goto-${name}.png`) });
  try { await walk(page, mark, shot, log); }
  catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  // release control, or the device stays locked to this (closed) browser session
  const rel = page.getByRole('button', { name: /^release$/i }).first();
  if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); await page.waitForTimeout(2000); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'goto.marks.json'), JSON.stringify({ marks }, null, 1));
})();
