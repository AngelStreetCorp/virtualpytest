// Assets for video 6 (why did it fail: the image comparison report), host-clone-1 + youtube-web, against prod.
// The search_results node carries an image check whose reference was taken on the home page, so a goto to
// search_results fails on it on purpose. Restore the node afterwards (see TASK-28, video 6).
// Usage: node cmp_capture.js [editor|goto|report <test report url>|all]
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path'); const https = require('https');
const DIR = __dirname; const OUT = path.join(DIR, 'raw6'); fs.mkdirSync(OUT, { recursive: true });
const TOKEN = fs.readFileSync(path.join(DIR, '.token'), 'utf8').trim();
const TEAM = '7fdeb4bb-3639-4ec3-959f-b54769a219ce';
const SERVER = 'https://virtualpytest.angelstreet.io'; const BASE = process.env.PROMO_BASE || SERVER;
const VIEW = { width: 1920, height: 1080 }; const mode = process.argv[2] || 'all';
const url = (p) => `${BASE}${p}${p.includes('?') ? '&' : '?'}auto_signed=${TOKEN}`;
const CURSOR = fs.readFileSync(path.join(DIR, 'capture.js'), 'utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];
const NODE = 'search_results';

function api(method, p, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(`${SERVER}${p}`); u.searchParams.set('auto_signed', TOKEN); u.searchParams.set('team_id', TEAM);
    const data = body ? JSON.stringify(body) : null;
    const headers = { 'User-Agent': 'Mozilla/5.0' };
    if (data) { headers['Content-Type'] = 'application/json'; headers['Content-Length'] = Buffer.byteLength(data); }
    const req = https.request(u, { method, headers }, res => {
      let s = ''; res.on('data', d => s += d); res.on('end', () => { try { resolve(JSON.parse(s)); } catch (e) { reject(new Error(s.slice(0, 200))); } });
    });
    req.on('error', reject); if (data) req.write(data); req.end();
  });
}
async function glide(page, x, y, pause = 500) { await page.mouse.move(x, y, { steps: 28 }); await page.waitForTimeout(pause); await page.mouse.click(x, y); }
async function closeToast(page) {
  const fab = page.locator('button[aria-label="Click to restore notification"]').first();
  if (await fab.count()) {
    await fab.click(); await page.waitForTimeout(700);
    const x = page.locator('.MuiAlert-root button').last();
    if (await x.count()) await x.click().catch(() => {});
    await page.waitForTimeout(500);
  }
}
async function record(name, fn) {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW, ignoreHTTPSErrors: true, recordVideo: { dir: path.join(OUT, 'video-' + name), size: VIEW } });
  await ctx.addInitScript(CURSOR);
  // R2 assets (reference thumbnails, report images) hit cross-origin isolation on a local dev server
  await ctx.route(/virtualpytest\.angelstreet\.io\/virtualpytest\/.*\.(jpg|jpeg|png|webp|mp4)/i, async route => {
    try { const r = await route.fetch(); await route.fulfill({ response: r, headers: { ...r.headers(), 'cross-origin-resource-policy': 'cross-origin', 'access-control-allow-origin': '*' } }); }
    catch (e) { await route.continue().catch(() => {}); }
  });
  const page = await ctx.newPage(); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  let extra = {};
  try { extra = (await fn(page, mark)) || {}; } catch (e) { console.log('clip', name, 'ERROR', e.message); await page.screenshot({ path: path.join(OUT, `${name}-error.png`) }).catch(() => {}); }
  const vid = page.video(); await ctx.close(); fs.copyFileSync(await vid.path(), path.join(OUT, `${name}.webm`));
  fs.writeFileSync(path.join(OUT, `${name}.marks.json`), JSON.stringify({ marks, ...extra }, null, 1)); await browser.close();
  console.log('clip', name, marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
  return extra;
}
const slow = async (page, px, n, pause = 900) => { for (let i = 0; i < n; i++) { await page.mouse.wheel(0, px); await page.waitForTimeout(pause); } };

// ---- 1. editor: fit view, take control, the node's edit dialog down to its verifications
async function editor() {
  await record('editor-cmp', async (page, mark) => {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2500);
    await page.goto(url('/navigation-editor/youtube-web'), { waitUntil: 'load', timeout: 180000 }); await page.mouse.move(960, 600);
    await page.locator('.react-flow__node').first().waitFor({ timeout: 120000 }); await page.waitForTimeout(5000);   // the dev-server frontend can take a minute
    await closeToast(page); mark('loaded');
    const fit = page.locator('button[title="fit view"]').first(); const fb = await fit.boundingBox(); await glide(page, fb.x + fb.width / 2, fb.y + fb.height / 2); await page.waitForTimeout(1500); mark('tidy');
    const sel = page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first();
    await sel.waitFor({ timeout: 120000 }); const sb = await sel.boundingBox();
    // the host list can take a while on the dev-server frontend: reopen the select until host-clone-1 is listed
    const opt = page.locator('[role="option"]').filter({ hasText: /host-clone-1/ }).first();
    for (let i = 0; i < 12; i++) {
      await glide(page, sb.x + sb.width / 2, sb.y + sb.height / 2); await page.waitForTimeout(900);
      if (await opt.count()) break;
      await page.keyboard.press('Escape'); await page.waitForTimeout(10000);
    }
    const ob = await opt.boundingBox(); await glide(page, ob.x + ob.width / 2, ob.y + ob.height / 2); await page.waitForTimeout(1500);
    const ctl = page.getByRole('button', { name: /^control$/i }).first(); const cb = await ctl.boundingBox(); await glide(page, cb.x + cb.width / 2, cb.y + cb.height / 2, 600); mark('control');
    for (let i = 0; i < 11; i++) { await page.waitForTimeout(5000); await page.mouse.move(700 + i * 15, 500, { steps: 8 }); }
    mark('stream');
    const n = page.locator(`.react-flow__node:has-text("${NODE}")`).first(); const nb = await n.boundingBox();
    await glide(page, nb.x + nb.width / 2, nb.y + 30, 700); await page.waitForTimeout(1800); mark('node');
    await page.screenshot({ path: path.join(OUT, 'editor-node.png') });
    const edit = page.getByRole('button', { name: /^edit$/i }).first(); await edit.waitFor({ timeout: 10000 });
    const eb = await edit.boundingBox(); await glide(page, eb.x + eb.width / 2, eb.y + eb.height / 2, 600); await page.waitForTimeout(3000); mark('dialog');
    await page.screenshot({ path: path.join(OUT, 'editor-node-dialog.png') });
    const ver = page.locator('[role="dialog"] >> text=/search_results_chips|waitForImageToAppear|wait For Image To Appear/').first();
    if (await ver.count()) {
      await ver.scrollIntoViewIfNeeded(); await page.waitForTimeout(600);
      const vb = await ver.boundingBox(); await page.mouse.move(vb.x + 40, vb.y + 10, { steps: 25 }); await page.waitForTimeout(3500); mark('verification');
    } else { await page.waitForTimeout(2000); mark('verification'); console.log('image verification row not found in the dialog'); }
    await page.screenshot({ path: path.join(OUT, 'editor-node-verification.png') });
    // the preview icon right of the reference select opens the reference image on hover
    const refSel = page.locator('[role="dialog"] .MuiInputBase-root:has-text("search_results_chips")').first();
    const rsb = await refSel.boundingBox().catch(() => null);
    if (rsb) {
      await page.mouse.move(rsb.x + rsb.width + 20, rsb.y + rsb.height / 2, { steps: 25 }); await page.waitForTimeout(4000); mark('reference');
      await page.screenshot({ path: path.join(OUT, 'editor-node-reference.png') });
    } else { mark('reference'); console.log('reference select not found'); }
    await page.mouse.move(1100, 540, { steps: 15 }); await page.waitForTimeout(1500); mark('verification-end');
    await page.keyboard.press('Escape'); await page.waitForTimeout(800);
    const rel = page.getByRole('button', { name: /release/i }).first(); if (await rel.count()) { await rel.click().catch(() => {}); await page.waitForTimeout(1000); }
    mark('end');
  });
}

// ---- 2. goto live: device modal open, goto search_results over the API (fails on the image check)
async function gotoLive() {
  return record('goto-cmp', async (page, mark) => {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2500);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 }); await page.mouse.move(960, 700); await page.waitForTimeout(8000); mark('loaded');
    const title = page.locator('text=/^host-clone-1$/').first(); await title.waitFor({ timeout: 60000 }); const tb = await title.boundingBox();
    await glide(page, tb.x + 120, tb.y + tb.height + 80, 600); mark('modal'); await page.waitForTimeout(4000);
    const start = await api('POST', '/server/script/execute', { host_name: 'host-clone-1', device_id: 'host', script_name: 'goto', parameters: `--userinterface youtube-web --node ${NODE}` });
    console.log('goto started', start.task_id, start.error || ''); mark('goto-start');
    let result = null;
    for (let i = 0; i < 160; i++) {
      await page.waitForTimeout(5000);
      if (i % 6 === 0) await page.mouse.move(900 + (i % 12) * 20, 600, { steps: 10 });
      const st = await api('GET', `/server/script/status/${start.task_id}`); const task = st.task || {};
      if (task.completed_at) { result = task.result; break; }
    }
    mark('goto-done'); await page.waitForTimeout(3000); mark('end');
    return { task_id: start.task_id, result };
  });
}

// ---- 3. test report: the failed step, its comparison link, then the comparison report, slowly
async function report(reportUrl) {
  return record('cmp-report', async (page, mark) => {
    // The comparison page is served by the host: a browser that has shown the device holds a
    // host-session cookie for it. Mint it the same way the frontend does before the walk (promo_lib).
    await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(1500);
    await require('./promo_lib')(OUT).mintHostSession(page, 'host-clone-1', BASE);
    await page.goto(reportUrl, { waitUntil: 'load', timeout: 180000 }); await page.mouse.move(1500, 400); await page.waitForTimeout(3500); mark('report');
    await page.screenshot({ path: path.join(OUT, 'test-report-top.png') });
    // the step row itself (the Error Details sentence also contains "home → search_results")
    const step = page.locator('[onclick*="toggleStep"]').filter({ hasText: 'home → search_results' }).first();
    for (let i = 0; i < 14; i++) { const sb = await step.boundingBox(); if (sb && sb.y < 330) break; await page.mouse.wheel(0, 150); await page.waitForTimeout(700); }
    const sb = await step.boundingBox(); await glide(page, sb.x + 60, sb.y + sb.height / 2, 900); await page.waitForTimeout(2200); mark('step');
    const link = page.locator('a:has-text("View comparison report")').first(); await link.waitFor({ timeout: 10000 });
    await link.scrollIntoViewIfNeeded(); await page.waitForTimeout(800); mark('steps-settled');
    // rest on the failed image check's score badge before following the link
    const badge = page.locator('text=/✗\s*65/').first(); const bgb = await badge.boundingBox({ timeout: 3000 }).catch(() => null);
    if (bgb) await page.mouse.move(bgb.x + bgb.width / 2, bgb.y + bgb.height / 2, { steps: 25 });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(OUT, 'test-report-step.png') });
    const href = await link.getAttribute('href');
    await link.evaluate(a => { a.target = '_self'; });   // new tab is not recorded; same content in this tab
    const lb = await link.boundingBox(); await glide(page, lb.x + lb.width / 2, lb.y + lb.height / 2, 1200); mark('link');
    await page.waitForLoadState('load').catch(() => {}); await page.mouse.move(1650, 60, { steps: 20 }); await page.waitForTimeout(4000); mark('cmp');
    await page.screenshot({ path: path.join(OUT, 'cmp-top.png') });
    await page.mouse.move(1100, 330, { steps: 25 }); await page.waitForTimeout(3000); mark('frames');     // first / best / last frames
    await slow(page, 140, 3, 1000); await page.waitForTimeout(2500); mark('full');                           // full frame, red box
    const src = page.locator('text=/CROPPED SOURCE/i').first(); const srb = await src.boundingBox();
    if (srb) { await page.mouse.move(srb.x + 150, srb.y + 40, { steps: 25 }); await page.waitForTimeout(3000); }
    mark('source');
    const ref = page.locator('text=/^REFERENCE$/i').first(); const rb = await ref.boundingBox();
    if (rb) { await page.mouse.move(rb.x + 150, rb.y + 40, { steps: 25 }); await page.waitForTimeout(3500); }
    mark('reference');
    const diff = page.locator('text=/PIXEL-DIFF/i').first(); const db = await diff.boundingBox();
    if (db) { await page.mouse.move(db.x + 150, db.y + 40, { steps: 25 }); await page.waitForTimeout(3500); }
    mark('diff'); await page.screenshot({ path: path.join(OUT, 'cmp-bottom.png') });
    await page.waitForTimeout(1500); mark('end');
    await page.screenshot({ path: path.join(OUT, 'cmp-full.png'), fullPage: true });   // after the walk: full-page capture re-lays out
    return { cmp_url: href };
  });
}

(async () => {
  if (mode === 'editor' || mode === 'all') await editor();
  let extra = null;
  if (mode === 'goto' || mode === 'all') extra = await gotoLive();
  if (mode === 'report' || mode === 'all') {
    let rep = process.argv[3];
    if (!rep && extra && extra.result) rep = extra.result.report_url;
    if (!rep && fs.existsSync(path.join(OUT, 'goto-cmp.marks.json'))) rep = (JSON.parse(fs.readFileSync(path.join(OUT, 'goto-cmp.marks.json'), 'utf8')).result || {}).report_url;
    if (rep) await report(rep); else console.log('no report url');
  }
})();
