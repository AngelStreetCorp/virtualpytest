// Subtitle QA promo (video 21): on the Run Tests page (main site, Server = RPI1-server) pick the vpt-pi4 local-video
// device and the script subtitle_qa, fill its parameters for the 2:25 Tears of Steel clip (CC BY 3.0, Blender
// Foundation), Run, watch the device stream while it plays (about 3m20s), then open the run report and its
// Subtitle Report through the app's own buttons and walk the sections.
// Lease first: ssh proxmox '~/bin/vpt-lease claim node1-vpt vpt-pi4/device1 --agent codebox:TASK-28-videos-subqa --purpose "subtitle QA promo take" --ttl 60'
// and release after. The clip and its sidecar files must be in /var/www/html/videos on vpt-pi4 (see TASK-28 section 21).
// Usage: node subqa_capture.js scout   -> raw21/scout-*.png (no run, no recording; safe without a lease)
//        node subqa_capture.js         -> raw21/subqa.mp4 + subqa.marks.json + take-*.png + take.log
// Marks: page, picked, params, run, playing, progress-N (every 30 s), passed, report, subreport, verdict, how-read,
//        not-counted, timeline, end.
// Env: SQ_SERVER (default RPI1-server), SQ_VIDEO, SQ_AUDIO, SQ_CREDITS (default 0).
// The Execution Logs are never opened. Reports are masked (IPs, key=value secrets) before they are filmed.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
process.env.PROMO_BASE = process.env.PROMO_BASE || 'https://virtualpytest.angelstreet.io';
const OUT = path.join(__dirname, 'raw21'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const SERVER = process.env.SQ_SERVER || 'RPI1-server';
const VIDEO = process.env.SQ_VIDEO || '/var/www/html/videos/tos_clip_subs_480p.mkv';
const AUDIO = process.env.SQ_AUDIO || '/var/www/html/videos/tos_clip_audio_words.json';
const CREDITS = process.env.SQ_CREDITS || '0';
const mode = process.argv[2]; const scout = mode === 'scout' || mode === 'report';   // report: scout of the report walk only, from the newest run in the list
const PFX = scout ? 'scout-' : 'take-';

async function clickBox(page, loc, pause = 600) {
  await loc.waitFor({ timeout: 30000 }); await loc.scrollIntoViewIfNeeded().catch(() => {});
  const b = await loc.boundingBox(); await glide(page, b.x + b.width / 2, b.y + b.height / 2, pause);
}

// same rules as campaign_report_capture.js: replace IPs and key=value secrets, refuse to go on if one is left
async function mask(page) {
  const left = await page.evaluate(() => {
    const re = [/(\b[A-Z0-9_]*(KEY|SECRET|TOKEN|PASS(WORD)?|USER|APP)\b\s*[=:]\s*)\S+/g, /(ip\s*=\s*)\d{1,3}(\.\d{1,3}){3}/gi, /()\b\d{1,3}(\.\d{1,3}){3}\b/g];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
    while ((n = walker.nextNode())) { let t = n.nodeValue; for (const r of re) t = t.replace(r, '$1••••••'); if (t !== n.nodeValue) n.nodeValue = t; }
    return /\b\d{1,3}(\.\d{1,3}){3}\b/.test(document.body.innerText);
  });
  if (left) throw new Error('an IP is still on the page');
}

async function pickServer(page, log) {
  const sel = page.locator('.MuiFormControl-root:has(label:has-text("Server")) .MuiSelect-select').first();
  await sel.waitFor({ timeout: 30000 });
  if ((await sel.innerText()).trim() === SERVER) return;
  await clickBox(page, sel, 700); await page.waitForTimeout(500);
  await clickBox(page, page.locator('[role="option"]').filter({ hasText: new RegExp(`^${SERVER}`) }).first(), 500);
  await page.waitForTimeout(9000); log('server: ' + (await sel.innerText()).trim());
}

// the stream tile under "Device Streams" is a thin strip: make it a tall 16:9 picture so the subtitle can be read
async function bigStream(page) {
  return page.evaluate(() => {
    let st = document.getElementById('sq-big-style'); if (!st) { st = document.createElement('style'); st.id = 'sq-big-style'; document.head.appendChild(st); }
    const v = document.querySelector('video'); if (!v) return 'no video';
    // the box = the first ancestor of the video that is a fixed-height strip (the stream tile); everything between is stretched to it
    let e = v, chain = [];
    while (e && e !== document.body) { chain.push(e); const r = e.getBoundingClientRect(); if (e !== v && r.width > 800 && r.height >= 100 && getComputedStyle(e).position === 'relative' && e.querySelector('video') && /^vpt-pi4:device1/.test((e.innerText || '').trim())) break; e = e.parentElement; }
    { let o = chain[chain.length - 1].parentElement, c = 0; while (o && c < 5) { o.setAttribute('data-sq-out', '1'); o = o.parentElement; c++; } }
    chain.forEach((n, k) => n.setAttribute(k === chain.length - 1 ? 'data-sq-box' : 'data-sq-in', '1'));
    st.textContent = '[data-sq-out]{height:auto !important;min-height:0 !important;max-height:none !important;grid-template-rows:none !important;grid-auto-rows:auto !important;contain:none !important} [data-sq-box]{height:620px !important;min-height:620px !important} [data-sq-in]{height:100% !important;min-height:0 !important;max-height:none !important} [data-sq-in][style*="absolute"],[data-sq-in]{inset:0 auto auto 0} video[data-sq-in]{width:100% !important;object-fit:contain !important;background:#000}';
    return 'ok chain=' + chain.length + ' h=' + Math.round(chain[chain.length - 1].getBoundingClientRect().height);
  });
}

async function centerStream(page) {
  const d = await page.evaluate(() => { const b = document.querySelector('[data-sq-box]'); return b ? b.getBoundingClientRect().top - 150 : 0; });
  for (let k = 0; k < 14; k++) { await page.mouse.wheel(0, d / 14); await page.waitForTimeout(50); }
}

async function walk(page, ctx, mark, shot, log, startRec) {
  if (mode === 'report') {
    await page.goto(url('/test-execution/run-tests'), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(8000);
    await pickServer(page, log); await page.waitForTimeout(6000); return reportWalk(page, ctx, mark, shot, log);
  }
  await page.goto(url('/test-execution/run-tests'), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(8000);
  await startRec(); mark('page'); await shot('page');
  await pickServer(page, log);
  await page.waitForTimeout(2500); await shot('server');

  // script first (picking a target first filters the list), then the target
  await clickBox(page, page.locator('text=/^Subtitle Qa$/').first(), 700);
  const filt = page.getByPlaceholder('Filter targets...');
  for (let attempt = 1; ; attempt++) {
    await clickBox(page, filt, 500); await page.keyboard.press('Control+A'); await page.keyboard.type('Smoke Loop', { delay: 70 }); await page.waitForTimeout(1500);
    if (await page.getByRole('checkbox').first().waitFor({ state: 'visible', timeout: 12000 }).then(() => true).catch(() => false)) break;
    if (attempt >= 5) throw new Error('the Smoke Loop Local target never appeared'); log('target list empty, retrying'); await page.waitForTimeout(8000);
  }
  await clickBox(page, page.getByRole('checkbox').first(), 800); await page.waitForTimeout(1500);
  if (!(await page.locator('body').innerText()).includes('1 targets selected') && !/1 target selected/.test(await page.locator('body').innerText())) log('warning: target count text not seen');
  mark('picked'); await shot('picked');

  // parameters: the form lists them per target; set video, audio_json and credits_from
  const field = async (name, value) => {
    const inp = page.getByLabel(name, { exact: true }).filter({ visible: true }).first();
    await clickBox(page, inp, 350); await page.keyboard.press('Control+A'); await page.keyboard.type(value, { delay: 18 }); await page.waitForTimeout(500);
  };
  await page.mouse.wheel(0, 300); await page.waitForTimeout(800);
  { const acc = page.locator('.MuiAccordionSummary-root').filter({ hasText: 'Subtitle Qa' }).first(); await acc.waitFor({ timeout: 20000 }); if ((await acc.getAttribute('aria-expanded')) !== 'true') await clickBox(page, acc.locator('.MuiAccordionSummary-expandIconWrapper').first(), 700); }
  await page.getByLabel('video', { exact: true }).filter({ visible: true }).first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(900);
  await field('video', VIDEO); await field('audio_json', AUDIO); await field('credits_from', CREDITS);
  await page.mouse.move(800, 300, { steps: 10 }); await page.waitForTimeout(1500);
  mark('params'); await shot('params');
  const vals = await page.evaluate(() => ['video', 'audio_json', 'credits_from', 'lang'].map(n => { const l = [...document.querySelectorAll('label')].find(x => x.textContent.trim() === n); const i = l && document.getElementById(l.getAttribute('for')); return n + '=' + (i ? i.value : '?'); }));
  log('params: ' + vals.join(' '));
  if (scout) {
    // the stream strip, sized for the take
    await clickBox(page, page.getByText('Show Streams').first(), 600); await page.waitForTimeout(6000);
    log('stream dom: ' + JSON.stringify(await page.evaluate(() => { const v = document.querySelector('video'); const out = []; let e = v; while (e && e !== document.body && out.length < 9) { const r = e.getBoundingClientRect(), c = getComputedStyle(e); out.push([e.tagName, (e.className + '').slice(0, 40), Math.round(r.width), Math.round(r.height), c.position, c.overflow, c.aspectRatio, c.height]); e = e.parentElement; } return out; })));
    log('big stream: ' + await bigStream(page));
    log('after: ' + JSON.stringify(await page.evaluate(() => { const out = []; let e = document.querySelector('video'); while (e && e !== document.body && out.length < 14) { const c = getComputedStyle(e), r = e.getBoundingClientRect(); out.push([e.tagName, (e.className + '').slice(-14), Math.round(r.height), c.gridAutoRows, c.gridTemplateRows, c.contain, c.maxHeight, c.overflow, c.position, c.display, e.hasAttribute('data-sq-box') ? 'BOX' : e.hasAttribute('data-sq-in') ? 'in' : '', e.getAttribute('style')]); e = e.parentElement; } return out; }))); await centerStream(page); await page.waitForTimeout(2500); await shot('stream-big');
    return;
  }

  // Run; the stream strip opens and grows while the film plays
  const rows = () => page.locator('table tbody tr').allInnerTexts();
  const before = (await rows())[0] || '';
  const alertsSeen = [];
  await clickBox(page, page.getByRole('button', { name: /^run$/i }).first(), 900); mark('run');
  const t0 = Date.now();
  await page.waitForTimeout(1500);
  await clickBox(page, page.getByText('Show Streams').first(), 700);
  await page.waitForTimeout(2000); log('big stream: ' + await bigStream(page)); await centerStream(page); await page.mouse.move(1500, 120, { steps: 15 });
  await page.waitForTimeout(6000); mark('playing'); await shot('playing');
  let verdict = null, lastProg = 0;
  for (let i = 0; i < 400 && !verdict; i++) {
    await page.waitForTimeout(1000);
    const sec = Math.round((Date.now() - t0) / 1000);
    if (sec - lastProg >= 30) { lastProg = sec; mark(`progress-${sec}`); await shot(`progress-${String(sec).padStart(3, '0')}`); }
    const al = await page.locator('[role="alert"], .MuiAlert-root').allInnerTexts().catch(() => []); for (const a of al) if (a.trim() && !alertsSeen.includes(a.trim())) { alertsSeen.push(a.trim()); log('ALERT on screen: ' + a.trim().replace(/\s+/g, ' ').slice(0, 200)); }
    const first = (await rows())[0] || '';
    if (first !== before && /subtitle_qa/.test(first)) { const m = /(Passed|Failed|Error|Aborted)/i.exec(first); if (m) verdict = m[1]; }
  }
  log(`run: ${verdict} after ~${Math.round((Date.now() - t0) / 1000)}s`);
  await page.waitForTimeout(2500); mark('passed'); await shot('passed');
  if (!/passed/i.test(verdict || '')) throw new Error('run ended ' + verdict + ', not Passed (retake)');

  await reportWalk(page, ctx, mark, shot, log);

}

async function reportWalk(page, ctx, mark, shot, log) {
  await page.evaluate(() => { const st = document.getElementById('sq-big-style'); if (st) st.textContent = ''; });
  let reportUrl = null;
  ctx.on('page', async p => { await p.waitForLoadState('domcontentloaded').catch(() => {}); reportUrl = p.url(); p.close().catch(() => {}); });
  await page.locator('table').first().scrollIntoViewIfNeeded(); await page.waitForTimeout(1200);
  const repBtn = page.locator('table tbody tr').first().locator('button, a').nth(0);
  const cells = page.locator('table tbody tr').first().locator('td');
  const reportCell = cells.nth(5); const rb = reportCell.locator('button, a, [role="button"]').first();
  await clickBox(page, (await rb.count()) ? rb : reportCell, 900);
  for (let i = 0; i < 30 && !reportUrl; i++) await page.waitForTimeout(500);
  if (!reportUrl) throw new Error('the Report button opened no tab');
  await page.goto(reportUrl, { waitUntil: 'load', timeout: 90000 }); await page.waitForTimeout(3500); await mask(page);
  mark('report'); await shot('report'); log('report host: ' + new URL(page.url()).host);
  await page.mouse.move(900, 400, { steps: 12 }); await page.waitForTimeout(3500);
  const link = page.locator("xpath=//*[normalize-space(text())='Subtitle Report:']/following::a[1]").first();
  await link.waitFor({ timeout: 20000 }); await link.scrollIntoViewIfNeeded(); await page.waitForTimeout(1200);
  const subHref = await link.getAttribute('href');
  reportUrl = null; await clickBox(page, link, 900);   // opens a tab: closed by the listener, the page itself follows below
  await page.waitForTimeout(1500);
  if (!subHref) throw new Error('no subtitle report link');
  await page.goto(subHref, { waitUntil: 'load', timeout: 90000 }); await page.waitForTimeout(3500); await mask(page);
  mark('subreport'); await shot('subreport'); log('subreport host: ' + new URL(page.url()).host);

  // walk the subtitle report: about 3-5 s per section
  const scrollToHeading = async (re, off = 90) => {
    const y = await page.evaluate(([src, off]) => { const h = [...document.querySelectorAll('h2, h3')].find(x => new RegExp(src, 'i').test(x.textContent)); return h ? h.getBoundingClientRect().top + scrollY - off : -1; }, [re.source, off]);
    if (y < 0) { log('heading not found: ' + re.source); return false; }
    const cur = await page.evaluate(() => scrollY); const steps = 14;
    for (let k = 1; k <= steps; k++) { await page.evaluate(v => window.scrollTo(0, v), cur + (y - cur) * k / steps); await page.waitForTimeout(60); }
    return true;
  };
  // a collapsed section (<details>) is opened with a click on its heading; the page is scrolled so the heading sits near the top first
  const openSection = async (re) => {
    const h = page.locator('h2, h3').filter({ hasText: new RegExp(re.source, 'i') }).first();
    const closed = await h.evaluate(el => { const d = el.closest('details'); return !!d && !d.open; }).catch(() => false);
    log('section ' + re.source + ' closed=' + closed + ' ' + await h.evaluate(el => el.outerHTML.slice(0, 120) + ' | parent ' + el.parentElement.tagName + ' ' + (el.closest('details') ? 'DETAILS' : 'nodetails')));
    if (closed) { const bb = await h.boundingBox(); await glide(page, bb.x + 60, bb.y + bb.height / 2, 700); await page.waitForTimeout(1200); log('now open=' + await h.evaluate(el => el.closest('details').open)); }
  };
  await page.mouse.move(800, 350, { steps: 20 }); await page.waitForTimeout(4000); mark('verdict');
  await page.evaluate(() => window.scrollTo(0, 260)); await page.waitForTimeout(2800);   // the six stat tiles
  await scrollToHeading(/how the subtitles were read/); await page.mouse.move(700, 450, { steps: 18 }); await page.waitForTimeout(4200); mark('how-read'); await shot('how-read');
  await scrollToHeading(/not counted/); await openSection(/not counted/); await scrollToHeading(/not counted/); await page.mouse.move(900, 500, { steps: 18 }); await page.waitForTimeout(5500); mark('not-counted'); await shot('not-counted');
  await mask(page);
  await scrollToHeading(/^\s*timeline/); await page.mouse.move(700, 450, { steps: 18 }); await page.waitForTimeout(3500); mark('timeline'); await shot('timeline');
  await scrollToHeading(/cue timing/); await openSection(/cue timing/); { const cb = page.getByLabel('show every cue'); if (await cb.count()) { await clickBox(page, cb.first(), 600); await page.waitForTimeout(800); } } await scrollToHeading(/cue timing/); await page.mouse.move(900, 500, { steps: 18 }); await page.waitForTimeout(4200); await shot('cue-timing');
  mark('end');
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await ctx.addInitScript(() => { try { localStorage.setItem('theme-mode', 'light'); } catch (e) {} });
  const page = await ctx.newPage();
  let stop = null; const marks = []; let t0 = Date.now(); const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  const startRec = async () => { if (!scout) stop = await startRecorder(page, 'subqa'); t0 = Date.now(); };
  const logf = path.join(OUT, scout ? 'scout.log' : 'take.log'); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${PFX}${name}.png`) });
  let failed = false;
  try { await walk(page, ctx, mark, shot, log, startRec); }
  catch (e) { failed = true; log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'subqa.marks.json'), JSON.stringify({ marks }, null, 1));
  console.log(marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
  if (failed) process.exitCode = 1;
})();
