// (zap scout, derived from tp_capture.js) Video 14, last beat (AI tests the interface it built): rpitest, the S21x phone (vpt-pi1 device1), interface
// `google-tv-mobile-ai`. Test Prompt page: pick target + interface, Control, type name/prompt/criteria, Explore,
// Run, live steps, PASS, then "Save as testcase" -> proposed steps -> Apply (the user CHOOSES to save), then Release.
// Lease vpt-pi1/device1 first (deploy skill).
// Usage: node tp_capture.js scout   -> raw14/scout-tp-*.png + scout-tp.log (no recording)
//        node tp_capture.js         -> raw14/tp.mp4 + tp.marks.json
// Env: TP_MODE=explore|graph (default explore)
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, process.env.OUT_DIR || 'raw14'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, BASE, url, CURSOR, redact, relay, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const SAVED = 'STB Live: zap 3 times'; const BOXES = [/^stb3 \(vpt-pi1\)/, new RegExp(process.env.BOX4 || "^stb4 \\(vpt-pi3\\)")];

async function clickBox(page, loc, pause = 600) {
  await loc.waitFor({ timeout: 30000 }); const b = await loc.boundingBox(); await glide(page, b.x + b.width / 2, b.y + b.height / 2, pause);
}
async function typeInto(page, label, text) {
  const f = page.getByLabel(label, { exact: true }).first(); await clickBox(page, f, 300); await page.keyboard.type(text, { delay: 45 });
}

// The page's stream panel is a fixed box bottom-left (560 px wide during a run, preview inside it a fixed 180 px
// high, no expand control on this page) and React re-renders it when the run starts: a page-side timer keeps
// widening it to 900 px and the preview to 420 px so the phone (centred, portrait) is ~420 CSS px tall and clear
// of the step list on the left; the panel's top stays below the form and result row.
async function bigStream(page, on) {
  return page.evaluate(([on, w, h]) => {
    clearInterval(window.__tpBig); document.querySelectorAll('[data-tp-big]').forEach(e => { e.style.removeProperty('width'); e.style.removeProperty('height'); e.removeAttribute('data-tp-big'); });
    if (!on) return true;
    const apply = () => {
      const el = [...document.querySelectorAll('div')].find(d => { const c = getComputedStyle(d); return c.position === 'fixed' && c.left === '4px' && c.bottom === '4px' && c.zIndex === '1300'; });
      if (!el) return false;
      el.setAttribute('data-tp-big', '1'); el.style.setProperty('width', w + 'px', 'important');
      for (const d of el.querySelectorAll('div')) if (getComputedStyle(d).height === '180px' || d.getAttribute('data-tp-big')) { d.setAttribute('data-tp-big', '1'); d.style.setProperty('height', h + 'px', 'important'); }
      return true;
    };
    window.__tpBig = setInterval(apply, 300); return apply();
  }, [on, 900, 420]);
}


// Test Prompt on set-top boxes: the saved prompt "STB Live: zap 3 times" runs as a graph on stb3 (vpt-pi1), then the
// same saved prompt replays on stb4 (vpt-pi3) with no AI call. A shot of the stream panel every 2 s per run lets the
// build find any operator logo to blur (the logo must never be on screen).
// Usage: node tp_zap_capture.js scout | node tp_zap_capture.js     (outputs raw14/{scout-,}tpz-*)
async function pickTarget(page, re) {
  for (let attempt = 1; ; attempt++) {
    await clickBox(page, page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first(), 900);
    const opt = page.locator('[role="option"]').filter({ hasText: re }).first();
    if (await opt.waitFor({ timeout: 10000 }).then(() => true).catch(() => false)) { await opt.scrollIntoViewIfNeeded(); await page.waitForTimeout(600); await clickBox(page, opt, 1000); return; }
    if (attempt >= 3) throw new Error('box never offered in Target');
    await page.keyboard.press('Escape'); await page.reload({ waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(9000);
  }
}

async function runOnce(page, mark, shot, log, tag, re) {
  // open the saved prompt first (loading it resets the Target to the box it last ran on), then pick the box
  await clickBox(page, page.getByText(SAVED, { exact: true }).first(), 900); await page.waitForTimeout(2000); mark(`${tag}-prompt`);
  await pickTarget(page, re); mark(`${tag}-target`); await page.waitForTimeout(1500); await shot(`${tag}-prompt`);
  const ctl = page.getByRole('button', { name: /^control$/i }).first();
  for (let i = 0; i < 20 && !(await ctl.isEnabled().catch(() => false)); i++) await page.waitForTimeout(1000);
  await clickBox(page, ctl); mark(`${tag}-control`);
  await page.getByLabel('Prompt', { exact: true }).first().waitFor({ timeout: 90000 }); await page.waitForTimeout(6000); await shot(`${tag}-control`);
  await clickBox(page, page.getByRole('button', { name: /^run graph$/i }).first(), 700); await page.waitForTimeout(800); await shot(`${tag}-mode`);
  log('big stream: ' + await bigStream(page, true));
  await clickBox(page, page.getByRole('button', { name: /^run$/i }).first(), 900); mark(`${tag}-run`);
  // shots of the stream panel every 2 s for the logo hunt (full 1920x1080 page, named by second since Run)
  const t0 = Date.now(); let stop = false;
  const sh = (async () => { let n = 0; while (!stop) { const sec = Math.round((Date.now() - t0) / 1000); await page.screenshot({ path: path.join(OUT, `${PFX}tpz-${tag}-s${String(sec).padStart(3, '0')}.png`) }).catch(() => {}); n++; await page.waitForTimeout(1500); } })();
  let verdict = null;
  for (let i = 0; i < 120 && !verdict; i++) {
    await page.waitForTimeout(2000);
    const body = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ');
    const v = (/\b(Passed|Failed|Error|Running|Queued)\s+\d{2}:\d{2}:\d{2}\b/.exec(body) || [])[1]; verdict = /^(passed|failed|error)$/i.test(v || '') ? v : null;   // newest result row: "Passed 06:21:40 Graph · v1"   // first card only: older runs sit below it
  }
  stop = true; await sh; const secs = Math.round((Date.now() - t0) / 1000);
  log(`${tag}: ${verdict} after ~${secs}s`); await bigStream(page, false); mark(`${tag}-${(verdict || 'none').toLowerCase()}`); await page.waitForTimeout(2500); await shot(`${tag}-result`);
  // expand the result card: the details rows say whether a graph was generated or a saved testcase was replayed
  await clickBox(page, page.locator('.MuiChip-root').filter({ hasText: /^Graph$/ }).first(), 900); await page.waitForTimeout(2500); await shot(`${tag}-details`);
  const det = (await page.locator('body').innerText()).replace(/\s+/g, ' '); log(`${tag} details: ${det.slice(det.toUpperCase().indexOf('RESULTS'), det.toUpperCase().indexOf('RESULTS') + 500)}`);
  await clickBox(page, page.getByRole('button', { name: /^release$/i }).first(), 900); await page.waitForTimeout(3000); mark(`${tag}-released`);
  return verdict;
}

async function walk(page, mark, shot, log) {
  await page.goto(url('/test-prompt'), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(8000);
  mark('page'); await shot('page');
  if (process.env.ONLY !== 'stb4') await runOnce(page, mark, shot, log, 'stb3', BOXES[0]);
  if (process.env.ONLY !== 'stb3') await runOnce(page, mark, shot, log, 'stb4', BOXES[1]);
}


// FLOW=fresh (default): a brand-new prompt typed on camera, Run graph (the AI compiles the sentence into a graph),
// PASS, Save as testcase, then Run graph again: the saved testcase replays with no AI call. OUT_DIR=raw17 for the take.
const NEWNAME = process.env.NEW_NAME || 'Live zap check';
const NEWPROMPT = 'Go to live TV, zap 3 times and check the picture moves after each zap';
const NEWCRIT = 'Each zap shows a moving picture';

async function watchRun(page, mark, shot, log, tag, onTick) {
  const t0 = Date.now(); let stop = false;
  const sh = (async () => { while (!stop) { const sec = Math.round((Date.now() - t0) / 1000); await page.screenshot({ path: path.join(OUT, `${PFX}tpz-${tag}-s${String(sec).padStart(3, '0')}.png`) }).catch(() => {}); await page.waitForTimeout(1500); } })();
  let verdict = null, compiled = false;
  for (let i = 0; i < 180 && !verdict; i++) {
    await page.waitForTimeout(2000);
    const body = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ');
    if (!compiled && /Navigation step|ENTRY/.test(body)) { compiled = true; mark(tag === 'run1' ? 'compiled' : 'replay-steps'); log(`${tag}: steps on screen after ${Math.round((Date.now() - t0) / 1000)}s`); }
    const v = (/\b(Passed|Failed|Error|Running|Queued)\s+\d{2}:\d{2}:\d{2}\b/.exec(body) || [])[1]; verdict = /^(passed|failed|error)$/i.test(v || '') ? v : null;   // newest result row: "Passed 06:21:40 Graph · v1"
  }
  stop = true; await sh; log(`${tag}: ${verdict} after ~${Math.round((Date.now() - t0) / 1000)}s`);
  if (!verdict || !/passed/i.test(verdict)) { await shot(`${tag}-notpassed`); throw new Error(`${tag} ended ${verdict}, not Passed (retake)`); }
  return verdict;
}

async function walkFresh(page, mark, shot, log) {
  await page.goto(url('/test-prompt'), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(8000);
  mark('page'); await shot('page');
  // new prompt: the + in the list header, then Target (after opening), Interface, Control
  await clickBox(page, page.locator('button:has([data-testid="AddCircleOutlineIcon"]), button:has([data-testid="AddIcon"]), button:has([data-testid="AddCircleIcon"])').first(), 900); await page.waitForTimeout(1200);
  mark('new-prompt');
  await pickTarget(page, BOXES[0]); mark('target'); await page.waitForTimeout(1200);
  await clickBox(page, page.locator('.MuiFormControl-root:has(label:has-text("Interface")) .MuiSelect-select').first(), 800);
  await page.waitForTimeout(2500);
  const io = page.locator('[role="option"]').filter({ hasText: new RegExp('^' + process.env.TP_UI + '$') }).first(); await io.scrollIntoViewIfNeeded(); await page.waitForTimeout(500); await clickBox(page, io, 1000);
  await page.waitForTimeout(800); if (!(await page.locator('.MuiSelect-select').filter({ hasText: new RegExp('^' + process.env.TP_UI + '$') }).count())) throw new Error('interface ' + process.env.TP_UI + ' not selected');
  mark('interface'); await shot('interface');
  const ctl = page.getByRole('button', { name: /^control$/i }).first();
  for (let i = 0; i < 20 && !(await ctl.isEnabled().catch(() => false)); i++) await page.waitForTimeout(1000);
  await clickBox(page, ctl); mark('control');
  await page.getByLabel('Prompt', { exact: true }).first().waitFor({ timeout: 90000 }); await page.waitForTimeout(6000); mark('stream'); await shot('control');
  await typeInto(page, 'Name', NEWNAME); await typeInto(page, 'Prompt', NEWPROMPT); await typeInto(page, 'Pass when', NEWCRIT);
  await page.waitForTimeout(800); mark('typed'); await shot('typed');
  await clickBox(page, page.getByRole('button', { name: /^run graph$/i }).first(), 700); await page.waitForTimeout(800);
  log('big stream: ' + await bigStream(page, true));
  await clickBox(page, page.getByRole('button', { name: /^run$/i }).first(), 900); mark('run-1');
  await watchRun(page, mark, shot, log, 'run1');
  await bigStream(page, false); mark('passed-1'); await page.waitForTimeout(3000); await shot('passed-1');
  const save = page.getByRole('button', { name: /save as testcase/i }).first();
  await clickBox(page, save, 1500); mark('save-click');
  const apply = page.getByRole('button', { name: /^apply$/i }).first();
  if (await apply.waitFor({ timeout: 6000 }).then(() => true).catch(() => false)) { await page.waitForTimeout(2500); await shot('proposal'); await clickBox(page, apply, 1200); mark('apply-click'); }
  await page.getByText(/Saved as testcase/i).first().waitFor({ timeout: 30000 }); await page.waitForTimeout(3000); mark('saved'); await shot('saved');
  const chip = await page.getByText(/^Replays /).first().innerText().catch(() => '?'); log('chip after save: ' + chip);
  log('big stream: ' + await bigStream(page, true));
  await page.waitForTimeout(500); await clickBox(page, page.getByRole('button', { name: /^run$/i }).first(), 900); mark('run-2');
  await watchRun(page, mark, shot, log, 'run2');
  await bigStream(page, false); mark('passed-2'); await page.waitForTimeout(2500); await shot('passed-2');
  await clickBox(page, page.getByText(/^Graph · v1/).first(), 900); await page.waitForTimeout(2500); mark('details'); await shot('details');
  const det = (await page.locator('body').innerText()).replace(/\s+/g, ' '); log('details: ' + det.slice(det.indexOf('Results'), det.indexOf('Results') + 520));
  await clickBox(page, page.getByRole('button', { name: /^release$/i }).first(), 900); await page.waitForTimeout(3000); mark('released'); await shot('released');
}

const PFX = process.argv[2] === 'scout' ? 'scout-' : 'take-';
(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await ctx.addInitScript(() => { try { localStorage.setItem('theme-mode', 'light'); } catch (e) {} }); await relay(ctx); const page = await ctx.newPage();
  const stop = scout ? null : await startRecorder(page, 'tpz');
  const marks = []; const t0 = Date.now(); const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  const logf = path.join(OUT, scout ? 'scout-tpz.log' : 'take.log'); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-tpz-${name}.png`) });
  page.on('console', m => { const t = m.text(); if (/useStream\].*(Fetching stream URL|Stream URL processed)|Stream URL processed/.test(t)) log('console: ' + t.slice(0, 240)); });
  try { await (process.env.FLOW === 'saved' ? walk : walkFresh)(page, mark, shot, log); }
  catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  // release control, or the device stays locked to this (closed) browser session
  const rel = page.getByRole('button', { name: /^release$/i }).first();
  if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); await page.waitForTimeout(2000); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'tpz.marks.json'), JSON.stringify({ marks }, null, 1));
})();
