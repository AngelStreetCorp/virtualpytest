// Assets for the 2048 video (TASK-33): the same AI plays 2048 on a phone (S21x on vpt-pi1) and in a
// browser (vpt-pi4) at the same time. One recording: the Device page already filtered to those two,
// both runs launched over the API (the game loads and plays in both tiles), the phone opened in big,
// then the phone run's report: its last move step expanded (AI call, swipe, decision) and its screenshot.
// rpitest; needs a local frontend pointed at it on PROMO_BASE (default http://localhost:5074,
// launch entry `frontend-rpitest-5074`), like zap_capture.js. The browser relays rpitest API calls and
// adds the CORS headers itself.
// Usage: node game_capture.js              -> raw12/game.mp4 + game.marks.json
//        node game_capture.js report <url> -> raw12/gamereport.mp4 (the report walk alone)
//        node game_capture.js grid         -> raw12/scout-*.png (filtered grid + phone modal, no run)
// GAME_MOVES (default 10), GAME_PLAYER (default llm), GAME_OPEN_AT (s after launch to open the phone, 45),
// GAME_HOLD (s the phone stays in big, 15).
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const DIR = __dirname; const OUT = path.join(DIR, 'raw12'); fs.mkdirSync(OUT, { recursive: true });
const { TOKEN, BASE, VIEW, VIEW_CSS, DPR, url, CURSOR, api, relay, scrubSecrets, startRecorder, glide } = require('./promo_lib')(OUT);
const PHONE = { host: 'vpt-pi1', device: 'device1', name: 'S21x', label: 'S21x - vpt-pi1' };
const WEB = { host: 'vpt-pi4', device: 'host', name: 'vpt-pi4_Host', label: 'vpt-pi4' };
const MOVES = process.env.GAME_MOVES || '10', PLAYER = process.env.GAME_PLAYER || 'llm';
const OPEN_AT = +(process.env.GAME_OPEN_AT || 45), HOLD = +(process.env.GAME_HOLD || 15);
// open the phone in big: click its tile on the zoomed grid, drop the zoom under the modal, switch to HD
async function openPhone(page) {
  const tb = await page.locator(`text=/^${PHONE.label}$/`).first().boundingBox();
  await glide(page, tb.x + tb.width / 2 + 60, tb.y + tb.height + 100, 700);
  const hd = page.locator('button[aria-label="High definition"]').first();
  if (await hd.isVisible({ timeout: 8000 }).catch(() => false)) { await page.waitForTimeout(1500); await glide(page, ...(await hd.boundingBox().then(b => [b.x + b.width / 2, b.y + b.height / 2])), 600); }
  else console.log('no HD button');
  await page.mouse.move(1500, 900, { steps: 20 });
}

const run = (d) => api('POST', '/server/script/execute', { host_name: d.host, device_id: d.device, script_name: 'game/game_2048', parameters: `--player ${PLAYER} --max_moves ${MOVES} --userinterface auto` });
async function waitDone(taskId, maxS = 600) {
  for (let i = 0; i < maxS / 5; i++) {
    const s = await api('GET', `/server/script/status/${taskId}`); const t = s.task || s;
    if (t.completed_at || ['completed', 'failed', 'error'].includes(t.status)) return t;
    await new Promise(r => setTimeout(r, 5000));
  }
  return null;
}
async function reportUrlOf(d, since) {
  const r = await api('GET', '/server/script-results/getAllScriptResults?limit=30');   // newest first, an array
  return (Array.isArray(r) ? r : []).find(x => x.script_name === 'game_2048' && x.host_name === d.host &&
    x.device_name === d.name && new Date(x.started_at) >= since && x.html_report_r2_url) || null;
}

// The report walk: summary, down to the last move step, expand it (AI call, swipe, the decision), open
// its screenshot. Works on any page already showing the report.
async function walkReport(page, mark) {
  await page.waitForFunction(() => document.querySelectorAll('[onclick*="toggleStep"]').length > 0, null, { timeout: 60000 });
  // the run was started over the API from this machine: its public IP is in the summary's Trigger line
  await scrubSecrets(page);
  await page.evaluate(() => { document.body.style.zoom = '1.3'; });   // report text is small for a video
  await page.mouse.move(1100, 60); await page.waitForTimeout(3500); mark('report');
  await page.screenshot({ path: path.join(OUT, 'report-top.png') });
  const moves = page.locator('[onclick*="toggleStep"]').filter({ hasText: /Move \d+:/ });
  const last = moves.last(); await last.waitFor({ timeout: 20000 });
  for (let i = 0; i < 40; i++) { const b = await last.boundingBox(); if (b && b.y < 300) break; await page.mouse.wheel(0, 160); await page.waitForTimeout(450); }
  await page.waitForTimeout(1200); mark('last-step');
  const detId = ((await last.getAttribute('onclick')) || '').match(/'([^']+)'/)[1];
  const lb = await last.boundingBox(); await glide(page, lb.x + 80, lb.y + lb.height / 2, 900); await page.waitForTimeout(1200);
  await page.locator(`#${detId}`).evaluate(e => e.scrollIntoView({ behavior: 'smooth', block: 'center' })); await page.waitForTimeout(2000); mark('expanded');
  await page.screenshot({ path: path.join(OUT, 'report-step.png') });
  // the expanded step: hover its actions, then its verification ("Decision and board")
  for (const re of [/ai\.gateway\.complete/, /swipe|press_key/, /Decision and board/]) {
    const l = page.getByText(re).last(); const b = await l.boundingBox().catch(() => null);
    if (b) { await page.mouse.move(b.x + 40, b.y + b.height / 2, { steps: 24 }); await page.waitForTimeout(2600); }
  }
  mark('details');
  // the settled-board thumbnail at the right of the expanded step (opens openScreenshotModal)
  const shot = page.locator(`#${detId} img[onclick*="openScreenshotModal"]`).first(); const sb = await shot.boundingBox().catch(() => null);
  if (sb) { await shot.scrollIntoViewIfNeeded(); const b = await shot.boundingBox(); await glide(page, b.x + b.width / 2, b.y + b.height / 2, 900); await page.waitForTimeout(3000); mark('screenshot');
    // the modal opens on the step-start frame: step to its last frame, the settled board
    const next = page.locator('[onclick*="navigateScreenshot(1)"]:visible').first();
    for (let i = 0; i < 4 && await next.count(); i++) { const nb = await next.boundingBox().catch(() => null); if (!nb) break; await glide(page, nb.x + nb.width / 2, nb.y + nb.height / 2, 700); await page.waitForTimeout(1800);
      if (/(\d+) \/ \1/.test(await page.locator('body').innerText())) break; }
    await page.waitForTimeout(2500); mark('settled'); }
  else console.log('no screenshot in the last step');
  await page.screenshot({ path: path.join(OUT, 'report-screenshot.png') }); await page.waitForTimeout(1500); mark('end');
}

async function newContext(browser) {
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR);
  // "previously filtered": the Device page's persisted Targets filter, set before the page loads
  await ctx.addInitScript(([origin, labels]) => {
    if (location.origin !== origin) return;
    localStorage.setItem('rec_filters_target', JSON.stringify(labels));
    localStorage.setItem('rec_filters_model', '[]'); localStorage.setItem('rec_filters_flag', '[]');
  }, [new URL(BASE).origin, [PHONE.label, WEB.label]]);
  await relay(ctx); return ctx;
}

async function reportOnly(reportUrl) {
  const browser = await chromium.launch({ headless: true }); const ctx = await newContext(browser);
  const page = await ctx.newPage(); const stop = await startRecorder(page, 'gamereport'); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  try { await page.goto(reportUrl, { waitUntil: 'load', timeout: 120000 }); await walkReport(page, mark); }
  catch (e) { console.log('ERROR', e.message.replaceAll(TOKEN, '<token>').slice(0, 200)); }
  await stop(); await ctx.close();
  fs.writeFileSync(path.join(OUT, 'gamereport.marks.json'), JSON.stringify({ marks, report_url: reportUrl }, null, 1)); await browser.close();
  console.log('clip gamereport', marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
}

async function scoutGrid() {
  const browser = await chromium.launch({ headless: true }); const ctx = await newContext(browser); const page = await ctx.newPage();
  try {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2000);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 });
    for (const d of [PHONE, WEB]) await page.locator(`text=/^${d.label}$/`).first().waitFor({ timeout: 90000 });
    for (const s of [20, 45, 70]) { await page.waitForTimeout(s === 20 ? 20000 : 25000); await page.screenshot({ path: path.join(OUT, `scout-grid-${s}s.png`) }); }
    await openPhone(page); await page.waitForTimeout(12000); await page.screenshot({ path: path.join(OUT, 'scout-phone-big.png') });
    await page.keyboard.press('Escape'); await page.waitForTimeout(2000); await page.screenshot({ path: path.join(OUT, 'scout-closed.png') });
  } catch (e) { console.log('ERROR', e.message.replaceAll(TOKEN, '<token>').slice(0, 200)); await page.screenshot({ path: path.join(OUT, 'scout-error.png') }).catch(() => {}); }
  await ctx.close(); await browser.close(); console.log('scout done');
}

(async () => {
  if (process.argv[2] === 'report') return reportOnly(process.argv[3]);
  if (process.argv[2] === 'grid') return scoutGrid();
  const locks = (await api('GET', '/server/control/lockedDevices')).locked_devices || {};
  for (const d of [PHONE, WEB]) if (locks[`${d.host}:${d.device}`]) { console.log(`${d.host}:${d.device} is locked, stop`); return; }
  const browser = await chromium.launch({ headless: true }); const ctx = await newContext(browser);
  const page = await ctx.newPage(); const stop = await startRecorder(page, 'game'); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  const extra = {};
  try {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2000);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 }); await page.mouse.move(960, 700);
    for (const d of [PHONE, WEB]) await page.locator(`text=/^${d.label}$/`).first().waitFor({ timeout: 90000 });
    // VNC tiles take 40-65 s to show; the build cuts this lead-in
    await page.waitForTimeout(65000); mark('grid');
    await page.screenshot({ path: path.join(OUT, 'grid-before.png') });
    const since = new Date(Date.now() - 5000);
    const [rp, rw] = await Promise.all([run(PHONE), run(WEB)]); mark('launched');
    extra.phone_task = rp.task_id; extra.web_task = rw.task_id; console.log('launched', rp.task_id, rw.task_id);
    if (!rp.task_id || !rw.task_id) throw new Error(`launch failed: ${JSON.stringify(rp).slice(0, 120)} ${JSON.stringify(rw).slice(0, 120)}`);
    for (let i = 0; i < OPEN_AT / 5; i++) { await page.waitForTimeout(5000); await page.mouse.move(800 + (i % 6) * 30, 640, { steps: 10 }); }
    mark('playing'); await page.screenshot({ path: path.join(OUT, 'grid-playing.png') });
    await openPhone(page); mark('open');
    await page.waitForTimeout(HOLD * 1000); mark('big'); await page.screenshot({ path: path.join(OUT, 'phone-big.png') });
    await page.keyboard.press('Escape'); await page.waitForTimeout(1500); mark('closed');
    const [dp, dw] = await Promise.all([waitDone(rp.task_id), waitDone(rw.task_id)]); mark('done');
    console.log('phone', dp && (dp.status || dp.result?.success), 'web', dw && (dw.status || dw.result?.success));
    let row = null; for (let i = 0; i < 12 && !row; i++) { row = await reportUrlOf(PHONE, since); if (!row) await page.waitForTimeout(5000); }
    if (!row || !row.html_report_r2_url) throw new Error('no phone report');
    extra.phone_report = row.html_report_r2_url; extra.phone_result = row.id; extra.phone_success = row.success;
    const webRow = await reportUrlOf(WEB, since); if (webRow) { extra.web_result = webRow.id; extra.web_success = webRow.success; }
    await page.goto(row.html_report_r2_url, { waitUntil: 'load', timeout: 120000 }); mark('page');
    await walkReport(page, mark);
  } catch (e) { console.log('ERROR', e.message.replaceAll(TOKEN, '<token>').slice(0, 200)); await page.screenshot({ path: path.join(OUT, 'game-error.png') }).catch(() => {}); }
  await stop(); await ctx.close();
  fs.writeFileSync(path.join(OUT, 'game.marks.json'), JSON.stringify({ marks, ...extra }, null, 1)); await browser.close();
  console.log('clip game', marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
