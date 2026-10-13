// Virtual Scripts promo (video 18): in the builder, paste the goto_live script, name it smoke_goto_live, save it,
// pick stb3 (vpt-pi1) + stb_tv, take control, Run, PASS, open the report and scroll it, release control.
// Lease vpt-pi1/device3 first (deploy skill). Main site loads directly (PROMO_BASE=https://virtualpytest.angelstreet.io).
// Usage: node vscript_capture.js scout   -> raw18/scout-vs-*.png + scout-vs.log (no recording)
//        node vscript_capture.js         -> raw18/vscript.mp4 + vscript.marks.json + take-vs-*.png + take.log
// Env: VS_NAME (default smoke_goto_live), VS_BOX (regex source for the Target option, default ^stb3 \(vpt-pi1\)),
//      VS_UI (default stb_tv), VS_SERVER (default RPI1-server), VS_NO_RUN=1 (stop after save, scout only),
//      VS_REUSE=1 (scout only: keep an already saved script of that name instead of deleting it).
// The Execution Logs of the run are never opened (they print secrets); the report is scrubbed (promo_lib scrubSecrets) before it is filmed.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
process.env.PROMO_BASE = process.env.PROMO_BASE || 'https://virtualpytest.angelstreet.io';
const OUT = path.join(__dirname, 'raw18'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, scrubSecrets, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const NAME = process.env.VS_NAME || 'smoke_goto_live';
const BOX = new RegExp(process.env.VS_BOX || '^stb3 \\(vpt-pi1\\)');
const UI = process.env.VS_UI || 'stb_tv';
const SERVER = process.env.VS_SERVER || 'RPI1-server';
const CODE = fs.readFileSync(path.join(OUT, 'smoke_goto_live.py'), 'utf8');
const scout = process.argv[2] === 'scout';
const PFX = scout ? 'scout-' : 'take-';

async function clickBox(page, loc, pause = 600) {
  await loc.waitFor({ timeout: 30000 }); await loc.scrollIntoViewIfNeeded().catch(() => {});
  const b = await loc.boundingBox(); await glide(page, b.x + b.width / 2, b.y + b.height / 2, pause);
}


async function pickServer(page, log) {
  const sel = page.locator('.MuiFormControl-root:has(label:has-text("Server")) .MuiSelect-select').first();
  await sel.waitFor({ timeout: 30000 });
  if ((await sel.innerText()).trim() === SERVER) return;
  await sel.click(); await page.waitForTimeout(800);
  await page.locator('[role="option"]').filter({ hasText: new RegExp(`^${SERVER}`) }).first().click();
  await page.waitForTimeout(9000); log('server: ' + (await sel.innerText()).trim());
}

// delete an earlier smoke_goto_live (from a scout) so the take creates it fresh
async function deleteExisting(page, log) {
  const item = page.getByText(NAME, { exact: true }).first();
  if (!(await item.isVisible().catch(() => false))) return;
  await item.click(); await page.waitForTimeout(1500);
  await page.locator('button:has([data-testid="MoreHorizIcon"])').first().click(); await page.waitForTimeout(600);
  await page.getByRole('menuitem', { name: /delete script/i }).click(); await page.waitForTimeout(600);
  await page.getByRole('button', { name: /^delete$/i }).click();
  for (let i = 0; i < 15 && await page.getByText(NAME, { exact: true }).first().isVisible().catch(() => false); i++) await page.waitForTimeout(1000);
  await page.waitForTimeout(2500);
  log('deleted earlier ' + NAME + ': ' + !(await page.getByText(NAME, { exact: true }).first().isVisible().catch(() => false)));
}

// the HDMI preview (fixed, bottom-left, over the script rail) is small: scale it up from its bottom-left corner while the box is driven
async function bigStream(page, on) {
  return page.evaluate(([on, k]) => {
    clearInterval(window.__vsBig); document.querySelectorAll('[data-vs-big]').forEach(e => e.removeAttribute('data-vs-big'));
    let st = document.getElementById('vs-big-style'); if (!st) { st = document.createElement('style'); st.id = 'vs-big-style'; document.head.appendChild(st); }
    st.textContent = on ? `[data-vs-big] { transform: scale(${k}) !important; transform-origin: bottom left !important; }` : '';
    if (!on) return true;
    const apply = () => {
      let el = [...document.querySelectorAll('h6')].find(x => /^HDMI/.test((x.innerText || '').trim()));
      while (el && !(getComputedStyle(el).position === 'absolute' && el.getBoundingClientRect().width > 150 && el.getBoundingClientRect().width < 400)) el = el.parentElement;
      if (!el) return false;
      el.setAttribute('data-vs-big', '1'); return true;
    };
    window.__vsBig = setInterval(apply, 200); return apply();
  }, [on, 2.3]);
}

async function walk(page, ctx, mark, shot, log, startRec) {
  // prep, not filmed: server, a clean list
  await page.goto(url('/builder/virtual-scripts'), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(8000);
  await pickServer(page, log);
  // (no reload from here on: a fresh load with another server selected lands on /login, the auto-sign token is not honoured there)
  await page.waitForTimeout(4000);
  if (!process.env.VS_REUSE) await deleteExisting(page, log);
  await startRec(); mark('builder'); await shot('builder');
  await page.waitForTimeout(2500);

  // new script
  await clickBox(page, page.locator('button:has([data-testid="AddIcon"])').first(), 800); await page.waitForTimeout(1200); mark('new-script');
  // name
  await clickBox(page, page.getByLabel('Name', { exact: true }).first(), 500); await page.keyboard.type(NAME, { delay: 70 }); await page.waitForTimeout(900);
  mark('named'); await shot('named');
  // paste: click into the editor, Ctrl+A, then the code lands as one clipboard paste
  const ed = page.locator('.cm-content').first();
  await clickBox(page, page.locator('.cm-line').filter({ hasText: /\S/ }).nth(2), 600);
  if (!(await page.evaluate(() => !!document.activeElement.closest('.cm-editor')))) { log('editor not focused after click, focusing'); await ed.focus(); } await page.keyboard.press('Control+A'); await page.waitForTimeout(900);
  await ed.evaluate((el, code) => { const dt = new DataTransfer(); dt.setData('text/plain', code); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); }, CODE);
  await page.waitForTimeout(1500); await page.keyboard.press('Control+Home'); await page.waitForTimeout(1200);
  const lines = await page.locator('.cm-line').count(); log('editor lines in DOM after paste: ' + lines);
  const txt = await page.locator('.cm-content').first().innerText(); if (!/Smart Navigation|VirtualPyTest/.test(txt)) throw new Error('paste did not land');
  mark('pasted'); await shot('pasted');
  await page.mouse.wheel(0, 500); await page.waitForTimeout(1200); await page.mouse.wheel(0, -500); await page.waitForTimeout(1200);
  // save
  await clickBox(page, page.getByRole('button', { name: /^save$/i }).first(), 800);
  if (await page.getByText('Unsaved').first().waitFor({ state: 'hidden', timeout: 10000 }).then(() => false).catch(() => true)) { log('first save did not take, clicking Save again'); await clickBox(page, page.getByRole('button', { name: /^save$/i }).first(), 600); }
  await page.getByText('Unsaved').first().waitFor({ state: 'hidden', timeout: 20000 }).catch(async e => { log('save toast: ' + (await page.locator('[role="alert"], .MuiAlert-root, .MuiSnackbar-root').allInnerTexts().catch(() => [])).join(' | ')); throw e; }); await page.waitForTimeout(2000);
  mark('saved'); await shot('saved');
  if (process.env.VS_NO_RUN) return;

  // target + interface
  for (let attempt = 1; ; attempt++) {
    await clickBox(page, page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first(), 900);
    const opt = page.locator('[role="option"]').filter({ hasText: BOX }).first();
    if (await opt.waitFor({ timeout: 10000 }).then(() => true).catch(() => false)) { await clickBox(page, opt, 1000); break; }
    if (attempt >= 3) throw new Error('box never offered in Target');
    await page.keyboard.press('Escape'); await page.waitForTimeout(9000);
  }
  await clickBox(page, page.locator('.MuiFormControl-root:has(label:has-text("Interface")) .MuiSelect-select').first(), 800); await page.waitForTimeout(1300);
  const io = page.locator('[role="option"]').filter({ hasText: new RegExp(`^${UI}$`) }).first(); await clickBox(page, io, 500);
  await page.waitForTimeout(800); mark('target'); await shot('target');
  const ctl = page.getByRole('button', { name: /^control$/i }).first();
  for (let i = 0; i < 20 && !(await ctl.isEnabled().catch(() => false)); i++) await page.waitForTimeout(1000);
  await clickBox(page, ctl, 700); mark('control');
  await page.getByRole('button', { name: /^release$/i }).first().waitFor({ timeout: 90000 }); await page.waitForTimeout(6000); await shot('control');
  log('hdmi chain: ' + JSON.stringify(await page.evaluate(() => { const out = []; let e = [...document.querySelectorAll('*')].filter(x => /^HDMI/.test((x.innerText || '').trim()) && x.children.length <= 3).pop(); while (e && e !== document.body) { const c = getComputedStyle(e), r = e.getBoundingClientRect(); out.push([e.tagName, c.position, c.left, c.bottom, Math.round(r.width), Math.round(r.height), c.transform]); e = e.parentElement; } return out; })));
  log('big stream: ' + await bigStream(page, true)); await page.waitForTimeout(1500);

  // run: the report opens in a new tab by itself; keep its URL, close the tab, and open the report on camera later
  let reportUrl = null;
  ctx.on('page', async p => { await p.waitForLoadState('domcontentloaded').catch(() => {}); reportUrl = p.url(); log('report tab opened (url kept)'); p.close().catch(() => {}); });
  await clickBox(page, page.getByRole('button', { name: /^run$/i }).first(), 900); mark('run');
  const t0 = Date.now(); let stop = false;
  const sh = (async () => { while (!stop) { const sec = Math.round((Date.now() - t0) / 1000); await page.screenshot({ path: path.join(OUT, `${PFX}vs-run-s${String(sec).padStart(3, '0')}.png`) }).catch(() => {}); await page.waitForTimeout(1500); } })();
  const clipBox = { x: 0, y: 380, width: 700, height: 520 };
  const fast = (async () => { while (!stop) { const sec = ((Date.now() - t0) / 1000).toFixed(1); await page.screenshot({ path: path.join(OUT, `${PFX}vs-panel-t${sec.padStart(5, '0')}.png`), clip: clipBox, scale: 'css' }).catch(() => {}); await page.waitForTimeout(150); } })();
  let marked = false, verdict = null;
  for (let i = 0; i < 150 && !verdict; i++) {
    await page.waitForTimeout(1000);
    if (!marked && (Date.now() - t0) > 3000) { marked = true; mark('running'); }
    const body = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ');
    const m = /Last run\s+(Passed|Failed|Error)/i.exec(body); verdict = m && m[1];
  }
  stop = true; await sh; await fast; const secs = Math.round((Date.now() - t0) / 1000);
  log(`run: ${verdict} after ~${secs}s (run starts at mark 'run'; shots take-vs-run-sNNN = seconds since Run)`);
  await bigStream(page, false); mark('passed'); await page.waitForTimeout(3000); await shot('passed');
  log('last run bar: ' + ((await page.locator('body').innerText()).match(/Last run[^\n]*\n?[^\n]*/) || [''])[0].replace(/\d{1,3}(\.\d{1,3}){3}/g, '•'));
  if (!/passed/i.test(verdict || '')) throw new Error('run ended ' + verdict + ', not Passed (retake)');

  // release the box before leaving the page, then open the report from the Last run bar
  await clickBox(page, page.getByRole('button', { name: /^release$/i }).first(), 800); await page.waitForTimeout(3000); mark('released');
  const rep = page.locator('a[aria-label="Report"]').first(); const href = reportUrl || await rep.getAttribute('href');
  await clickBox(page, rep, 900);   // the tab it opens is closed by the listener above
  await page.waitForTimeout(1500);
  if (!href) throw new Error('no report url');
  await page.goto(href, { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(3500); await scrubSecrets(page);
  mark('report'); await shot('report'); log('report url host: ' + new URL(page.url()).host);
  // summary stays on screen a moment, then the step screenshots (Test Mosaic) open and the page scrolls; never the Execution Logs
  await page.mouse.move(900, 400, { steps: 12 }); await page.waitForTimeout(3500);
  mark('report-scrolled');
  const mos = page.getByText(/Test Mosaic/).first();
  if (await mos.isVisible().catch(() => false)) { await page.mouse.wheel(0, 300); await page.waitForTimeout(1200); await clickBox(page, mos, 800); await page.waitForTimeout(2500); await scrubSecrets(page); }
  await page.screenshot({ path: path.join(OUT, `${PFX}vs-report-mosaic0.png`) });
  const h = await page.evaluate(() => document.documentElement.scrollHeight); log('report height: ' + h);
  let y = 0, k = 0;
  while (y < h - 700 && k < 6) {
    await page.mouse.wheel(0, 330); y += 330; k++; await page.waitForTimeout(1300);
    await page.screenshot({ path: path.join(OUT, `${PFX}vs-report-y${String(y).padStart(5, '0')}.png`) }).catch(() => {});
  }
  await page.waitForTimeout(1500); mark('end');
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await ctx.addInitScript(() => { try { localStorage.setItem('theme-mode', 'light'); } catch (e) {} });
  // the Scripts rail also lists other teams' fleet scripts and CI leftovers: hide those rows (and folders left empty) before anything is filmed
  await ctx.addInitScript(() => {
    const tidy = () => {
      for (const it of document.querySelectorAll('div[title]')) if (/^(labox|zz_ci_)/i.test(it.getAttribute('title') || '') && it.style.display !== 'none') it.style.display = 'none';
      for (const hd of document.querySelectorAll('p')) {
        const m = /^(.*) · (\d+)$/.exec(hd.textContent || ''); if (!m) continue;
        const folder = hd.parentElement && hd.parentElement.parentElement; if (!folder || !folder.children[1]) continue;
        if (/^labox/i.test(m[1])) { folder.style.display = 'none'; continue; }
        const vis = [...folder.querySelectorAll('div[title]')].filter(e => e.style.display !== 'none').length;
        if (folder.children[1].querySelector('div[title]')) { if (vis === 0) folder.style.display = 'none'; else { if (folder.style.display === 'none') folder.style.display = ''; if (String(vis) !== m[2]) hd.textContent = `${m[1]} · ${vis}`; } }
      }
    };
    new MutationObserver(tidy).observe(document, { childList: true, subtree: true, characterData: true });
  });
  const page = await ctx.newPage();
  let stop = null; const marks = []; let t0 = Date.now(); const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  const startRec = async () => { if (!scout) stop = await startRecorder(page, 'vscript'); t0 = Date.now(); };
  const logf = path.join(OUT, scout ? 'scout-vs.log' : 'take.log'); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${PFX}vs-${name}.png`) });
  let failed = false;
  try { await walk(page, ctx, mark, shot, log, startRec); }
  catch (e) { failed = true; log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  if (stop) await stop();
  // never leave the box locked to this (closing) browser session
  try {
    const rel = page.getByRole('button', { name: /^release$/i }).first();
    if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); await page.waitForTimeout(2500); log('released in cleanup'); }
  } catch (e) {}
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'vscript.marks.json'), JSON.stringify({ marks }, null, 1));
  console.log(marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
  if (failed) process.exitCode = 1;
})();
