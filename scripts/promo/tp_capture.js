// Video 14, last beat (AI tests the interface it built): rpitest, the S21x phone (vpt-pi1 device1), interface
// `google-tv-mobile-ai`. Test Prompt page: pick target + interface, Control, type name/prompt/criteria, Explore,
// Run, live steps, PASS, then "Save as testcase" -> proposed steps -> Apply (the user CHOOSES to save), then Release.
// Lease vpt-pi1/device1 first (deploy skill).
// Usage: node tp_capture.js scout   -> raw14/scout-tp-*.png + scout-tp.log (no recording)
//        node tp_capture.js         -> raw14/tp.mp4 + tp.marks.json
// Env: TP_MODE=explore|graph (default explore)
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw14'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, BASE, url, CURSOR, redact, relay, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const UI = 'google-tv-mobile-ai'; const TARGET = /S21x/; const MODE = process.env.TP_MODE || 'explore';
const NAME = 'Google TV tabs - AI generated';
const PROMPT = process.env.TP_PROMPT || 'Open Library, then Search, and check each screen opens.';
const CRITERIA = process.env.TP_CRITERIA || 'Library and Search screens each open';

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

async function walk(page, mark, shot, log) {
  await page.goto(url('/test-prompt'), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(8000);
  mark('page'); await shot('page');
  // rpitest's tunnel drops now and then: empty Target list -> reload and retry (3 times)
  for (let attempt = 1; ; attempt++) {
    await clickBox(page, page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first(), 900);
    const opt = page.locator('[role="option"]').filter({ hasText: TARGET }).first();
    if (await opt.waitFor({ timeout: 10000 }).then(() => true).catch(() => false)) { await clickBox(page, opt, 1200); break; }
    if (attempt >= 3) throw new Error('S21x never offered in Target (server offline?)');
    log(`Target empty, reload (attempt ${attempt})`); await page.keyboard.press('Escape');
    await page.reload({ waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(9000);
  }
  mark('target'); await page.waitForTimeout(1500);
  await clickBox(page, page.locator('.MuiFormControl-root:has(label:has-text("Interface")) .MuiSelect-select').first(), 800);
  await page.waitForTimeout(2500);   // the list fills and re-renders after it opens: measure the option only once it is still
  await clickBox(page, page.locator('[role="option"]').filter({ hasText: new RegExp(`^${UI}$`) }).first(), 1200);
  await page.waitForTimeout(800);
  if (!(await page.locator('.MuiSelect-select').filter({ hasText: UI }).count())) throw new Error('interface not selected');
  mark('interface'); await shot('interface');
  const ctl = page.getByRole('button', { name: /^control$/i }).first();
  for (let i = 0; i < 20 && !(await ctl.isEnabled().catch(() => false)); i++) await page.waitForTimeout(1000);
  await clickBox(page, ctl); mark('control');
  await page.getByLabel('Prompt', { exact: true }).first().waitFor({ timeout: 90000 }); await page.waitForTimeout(6000);
  mark('stream'); await shot('control');
  await typeInto(page, 'Name', NAME);
  await typeInto(page, 'Prompt', PROMPT);
  await typeInto(page, 'Acceptance Criteria', CRITERIA);
  await page.waitForTimeout(800); mark('typed'); await shot('typed');
  const modeBtn = page.getByRole('button', { name: MODE === 'graph' ? /^run graph$/i : /^explore$/i }).first();
  await clickBox(page, modeBtn, 700); await page.waitForTimeout(800);
  await clickBox(page, page.getByRole('button', { name: /^run$/i }).first(), 900); mark('run');
  await page.waitForTimeout(2500); await shot('after-run'); log('alerts: ' + (await page.locator('[role="alert"], .MuiSnackbar-root').allInnerTexts().catch(() => [])).join(' | '));
  log('big stream: ' + await bigStream(page, true)); await page.waitForTimeout(1500); await shot('big');
  // run: poll until the result card is complete (Save as testcase offered, or a failed/error chip)
  const save = page.getByRole('button', { name: /save as testcase/i }).first();
  const t0 = Date.now(); let done = false;
  for (let i = 0; i < 180; i++) {
    await page.waitForTimeout(5000);
    if (i % 3 === 2) await shot(`run-${String(i + 1).padStart(3, '0')}`);
    const body = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ');
    log(`t+${(i + 1) * 5}s save=${await save.isVisible().catch(() => false)} tail=${body.slice(body.toUpperCase().indexOf('RESULTS'), body.toUpperCase().indexOf('RESULTS') + 160)}`);
    const verdict = (/RESULTS\s+(Passed|Failed|Error)\b/i.exec(body) || [])[1];
    if (verdict && /passed/i.test(verdict) && await save.isVisible().catch(() => false)) { done = true; break; }
    if (verdict) { await shot('run-failed'); throw new Error(`run ended ${verdict}, not Passed (retake)`); }
  }
  if (!done) throw new Error('run never completed');
  log(`run took ${((Date.now() - t0) / 1000).toFixed(0)}s`); await bigStream(page, false); mark('passed'); await page.waitForTimeout(3000); await shot('passed');
  await clickBox(page, save, 1500); mark('save-click');
  // Explore: the save builds a testcase proposal (steps + checks) that is applied with a second click; Run graph saves at once
  const apply = page.getByRole('button', { name: /^apply$/i }).first();
  if (MODE === 'explore') {
    await apply.waitFor({ timeout: 120000 }); await page.waitForTimeout(3000); mark('proposal'); await shot('proposal');
    await clickBox(page, apply, 1200); mark('apply-click');
  }
  await page.getByText(/Saved as testcase/i).first().waitFor({ timeout: 30000 }); await page.waitForTimeout(3500);
  mark('saved'); await shot('saved');
  const rel = page.getByRole('button', { name: /^release$/i }).first();
  await clickBox(page, rel, 900); await page.waitForTimeout(3000); mark('released'); await shot('released');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await relay(ctx); const page = await ctx.newPage();
  const stop = scout ? null : await startRecorder(page, 'tp');
  const marks = []; const t0 = Date.now(); const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  const logf = path.join(OUT, `${scout ? 'scout' : 'take'}-tp.log`); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-tp-${name}.png`) });
  page.on('console', m => { const t = m.text(); if (/useStream\].*(Fetching stream URL|Stream URL processed)|Stream URL processed/.test(t)) log('console: ' + t.slice(0, 240)); });
  try { await walk(page, mark, shot, log); }
  catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  // release control, or the device stays locked to this (closed) browser session
  const rel = page.getByRole('button', { name: /^release$/i }).first();
  if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); await page.waitForTimeout(2000); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'tp.marks.json'), JSON.stringify({ marks }, null, 1));
})();
