// Video 14 (AI builds an interface): rpitest, the S21x phone (vpt-pi1 device1) with the Google TV app open on its
// home page, the empty `google-tv-mobile-ai` interface. Navigation editor: target S21x, Control, AI Generate,
// Start; the exploration runs for minutes (the build fast-forwards it), then Create Nodes/Edges and the
// validation run. Lease vpt-pi1/device1 first (deploy skill).
// Usage: node aigen_capture.js scout   -> raw14/scout-*.png every POLL s + scout.log (no recording)
//        node aigen_capture.js         -> raw14/aigen.mp4 + aigen.marks.json
// STOP_AT=proposals stops once the proposals are shown (default: run through validation and save).
// CLICK_SEQ overrides the buttons clicked after Create (default: Start Validation|Review Node Verifications|Save|Confirm & Save).
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw14'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, BASE, url, CURSOR, redact, relay, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const UI = 'google-tv-mobile-ai'; const TARGET = /S21x/; const POLL = 15;
const STOP_AT = process.env.STOP_AT || 'validation';

async function clickBox(page, loc, pause = 600) {
  await loc.waitFor({ timeout: 30000 }); const b = await loc.boundingBox(); await glide(page, b.x + b.width / 2, b.y + b.height / 2, pause);
}

async function walk(page, mark, shot, log) {
  await page.goto(url(`/navigation-editor/${UI}`), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(9000);
  mark('editor'); await shot('editor');
  // rpitest goes through a Cloudflare tunnel that drops now and then: if the page loaded while it was down, the
  // server shows offline and the Target list is empty. Reload and try again (3 times) instead of failing the take.
  for (let attempt = 1; ; attempt++) {
    await clickBox(page, page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first(), 900);
    const opt = page.locator('[role="option"]').filter({ hasText: TARGET }).first();
    if (await opt.waitFor({ timeout: 10000 }).then(() => true).catch(() => false)) { await clickBox(page, opt, 1500); break; }
    if (attempt >= 3) throw new Error('S21x never offered in Target (server offline?)');
    log(`Target empty, reload (attempt ${attempt})`); await page.keyboard.press('Escape');
    await page.reload({ waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(9000);
  }
  mark('target');
  await clickBox(page, page.getByRole('button', { name: /^control$/i }).first()); mark('control');
  await page.waitForTimeout(20000); mark('stream'); await shot('control');
  await clickBox(page, page.getByRole('button', { name: /build map|ai generate/i }).first(), 900); await page.waitForTimeout(2500);
  mark('modal'); await shot('modal');
  await clickBox(page, page.getByRole('button', { name: /^start$/i }).first()); mark('start');
  // exploration: poll until the proposals are shown (Create Nodes/Edges) or an error / 30 min
  const create = page.getByRole('button', { name: /create nodes\/edges/i }).first();
  for (let i = 0; i < 120; i++) {
    await page.waitForTimeout(POLL * 1000);
    const chips = await page.locator('.MuiDialog-root .MuiChip-label').allInnerTexts().catch(() => []);
    log(`t+${(i + 1) * POLL}s chips=${chips.join(' | ').slice(0, 200)}`);
    if (i % 4 === 3) await shot(`explore-${String(i + 1).padStart(3, '0')}`);
    if (await create.isVisible().catch(() => false)) break;
    if (await page.getByText(/error|failed/i).first().isVisible().catch(() => false)) { log('error text visible'); await shot('explore-error'); }
  }
  mark('proposals'); await shot('proposals');
  // "4 TVs nearby" is Google TV's cast picker, not a screen: untick it (its chip's delete icon)
  for (const label of (process.env.UNTICK || '4 TVs nearby|4_tvs_nearby').split('|')) {
    const chip = page.locator('.MuiDialog-root .MuiChip-root').filter({ hasText: new RegExp(label.replace(/[ _]/g, '[ _]'), 'i') }).first();
    if (await chip.isVisible().catch(() => false)) { const del = chip.locator('.MuiChip-deleteIcon'); await clickBox(page, (await del.count()) ? del : chip, 900); log(`unticked ${label}`); }
  }
  await page.waitForTimeout(1200); mark('unticked'); await shot('unticked');
  if (STOP_AT === 'proposals') return;
  await clickBox(page, create); mark('create');
  // after Create (TASK-40, BUG-0286): a "Start Validation" prompt (not a MuiDialog, so looked up page-wide), the edge
  // validation (~2 min), "Review Node Verifications", "Save" (one per node) and "Confirm & Save"
  const seq = (process.env.CLICK_SEQ || 'Start Validation|Review Node Verifications|Save|Confirm & Save').split('|');
  let lastTxt = '';
  for (let i = 0; i < 120 && seq.length; i++) {
    await page.waitForTimeout(5000);
    const dlg = page.locator('.MuiDialog-root').last();
    const txt = (await dlg.innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 240);
    if (txt !== lastTxt) { log(`t+${(i + 1) * 5}s ${txt}`); lastTxt = txt; if (i % 2 === 0) await shot(`after-${String(i + 1).padStart(3, '0')}`); }
    const name = seq[0], exact = new RegExp(`^\\s*${name.replace(/[&]/g, '\\&')}\\b`, 'i');
    const btn = (/^start validation$/i.test(name) ? page : dlg).getByRole('button', { name: exact }).last();   // only the prompt lives outside a dialog
    if (await btn.isVisible().catch(() => false) && await btn.isEnabled().catch(() => false)) {
      await clickBox(page, btn, 900); mark(`click-${name.replace(/\W+/g, '-').toLowerCase()}`); log(`clicked ${name}`); seq.shift();
    }
  }
  if (seq.length) log(`not reached: ${seq.join(' | ')}`);
  await page.waitForTimeout(4000); mark('saved'); await shot('saved');
  // the tree the AI built: wait for the modal to close, then the editor's own Auto Layout
  for (let i = 0; i < 20 && await page.locator('.MuiDialog-root').last().isVisible().catch(() => false); i++) await page.waitForTimeout(1000);
  const layout = page.locator('button[title="Auto Layout"]').first();
  if (await layout.isVisible().catch(() => false)) { await clickBox(page, layout, 800); await page.waitForTimeout(3500); }
  mark('tree'); await shot('tree');
  await page.waitForTimeout(2000); mark('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await relay(ctx); const page = await ctx.newPage();
  const stop = scout ? null : await startRecorder(page, 'aigen');
  const marks = []; const t0 = Date.now(); const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  const logf = path.join(OUT, `${scout ? 'scout' : 'take'}.log`); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-${name}.png`) });
  try { await walk(page, mark, shot, log); }
  catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  // release control, or the device stays locked to this (closed) browser session and the next run cannot select it
  const rel = page.getByRole('button', { name: /^release$/i }).first();
  if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); await page.waitForTimeout(2000); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'aigen.marks.json'), JSON.stringify({ marks }, null, 1));
})();
