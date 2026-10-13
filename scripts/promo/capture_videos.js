// Assets for video 1 (navigation) and video 2 (evidence), all on host-clone-1 + youtube-web.
// Usage: node capture_videos.js [editor|goto|report|all]
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs');
const path = require('path');
const https = require('https');

const DIR = __dirname;
const OUT = path.join(DIR, 'raw2');
fs.mkdirSync(OUT, { recursive: true });
const TOKEN = fs.readFileSync(path.join(DIR, '.token'), 'utf8').trim();
const TEAM = '7fdeb4bb-3639-4ec3-959f-b54769a219ce';
const SERVER = 'https://virtualpytest.angelstreet.io';
const BASE = 'http://localhost:5073';
const VIEW = { width: 1920, height: 1080 };
const mode = process.argv[2] || 'all';
const url = (p) => `${BASE}${p}${p.includes('?') ? '&' : '?'}auto_signed=${TOKEN}`;
const CURSOR = fs.readFileSync(path.join(DIR, 'capture.js'), 'utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];

function api(method, p, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(`${SERVER}${p}`); u.searchParams.set('auto_signed', TOKEN); u.searchParams.set('team_id', TEAM);
    const data = body ? JSON.stringify(body) : null;
    const req = https.request(u, { method, headers: data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {} }, res => {
      let s = ''; res.on('data', d => s += d); res.on('end', () => { try { resolve(JSON.parse(s)); } catch (e) { reject(new Error(s.slice(0, 200))); } });
    });
    req.on('error', reject); if (data) req.write(data); req.end();
  });
}
async function glide(page, x, y, pause = 500) { await page.mouse.move(x, y, { steps: 28 }); await page.waitForTimeout(pause); await page.mouse.click(x, y); }
async function dragNode(page, label, dx, dy) {
  const n = page.locator(`.react-flow__node:has-text("${label}")`).first();
  const bb = await n.boundingBox(); const x = bb.x + bb.width / 2, y = bb.y + 28; // grab the title bar
  await page.mouse.move(x, y, { steps: 20 }); await page.mouse.down(); await page.waitForTimeout(150);
  await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 18 }); await page.mouse.move(x + dx, y + dy, { steps: 18 });
  await page.waitForTimeout(150); await page.mouse.up(); await page.waitForTimeout(500);
}
async function record(name, fn) {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW, ignoreHTTPSErrors: true, recordVideo: { dir: path.join(OUT, 'video-' + name), size: VIEW } });
  await ctx.addInitScript(CURSOR);
  // R2 assets (report thumbnails etc.) hit cross-origin isolation on the dev server
  await ctx.route(/virtualpytest\.angelstreet\.io\/virtualpytest\/.*\.(jpg|jpeg|png|webp|mp4)/i, async route => {
    try { const r = await route.fetch(); await route.fulfill({ response: r, headers: { ...r.headers(), 'cross-origin-resource-policy': 'cross-origin', 'access-control-allow-origin': '*' } }); }
    catch (e) { await route.continue(); }
  });
  const page = await ctx.newPage(); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  let extra = {};
  try { extra = (await fn(page, mark)) || {}; } catch (e) { console.log('clip', name, 'ERROR', e.message); }
  const vid = page.video(); await ctx.close(); fs.copyFileSync(await vid.path(), path.join(OUT, `${name}.webm`));
  fs.writeFileSync(path.join(OUT, `${name}.marks.json`), JSON.stringify({ marks, ...extra }, null, 1)); await browser.close();
  console.log('clip', name, marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
  return extra;
}

// ---- 1. editor: fit, tidy the layout by dragging, attach the device
async function editor() {
  await record('editor', async (page, mark) => {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(2500);
    await page.goto(url('/navigation-editor/youtube-web'), { waitUntil: 'load', timeout: 60000 }); await page.mouse.move(960, 600); await page.waitForTimeout(9000); mark('loaded');
    const fit = page.locator('button[title="fit view"]').first(); const fb = await fit.boundingBox(); await glide(page, fb.x + fb.width / 2, fb.y + fb.height / 2); await page.waitForTimeout(1200); mark('fit');
    // tidy: pull search_results to the right, video_player above it, shorts to the left
    await dragNode(page, 'search_results', 520, 0); mark('drag1');
    await dragNode(page, 'video_player', 720, -40); mark('drag2');
    await dragNode(page, 'shorts', -300, 0); mark('drag3');
    await glide(page, fb.x + fb.width / 2, fb.y + fb.height / 2); await page.waitForTimeout(1500); mark('fit2');
    await page.screenshot({ path: path.join(OUT, 'editor-tidy.png') });
    // attach the device
    const sel = page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first();
    const sb = await sel.boundingBox(); await glide(page, sb.x + sb.width / 2, sb.y + sb.height / 2); await page.waitForTimeout(900);
    const opt = page.locator('[role="option"]').filter({ hasText: /host-clone-1/ }).first(); const ob = await opt.boundingBox(); await glide(page, ob.x + ob.width / 2, ob.y + ob.height / 2); await page.waitForTimeout(1500); mark('target');
    const ctl = page.getByRole('button', { name: /^control$/i }).first(); const cb = await ctl.boundingBox(); await glide(page, cb.x + cb.width / 2, cb.y + cb.height / 2, 600); mark('control');
    await page.waitForTimeout(7000);
    await page.mouse.move(700, 500, { steps: 30 }); await page.waitForTimeout(2000); mark('end');
    await page.screenshot({ path: path.join(OUT, 'editor-control.png') });
    const rel = page.getByRole('button', { name: /release/i }).first(); if (await rel.count()) { await rel.click().catch(() => {}); await page.waitForTimeout(1000); }
  });
}

// ---- 2. goto live: open the device stream, launch goto over the API, record until it completes
async function gotoLive() {
  return record('goto-live', async (page, mark) => {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(2500);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 60000 }); await page.mouse.move(960, 700); await page.waitForTimeout(8000); mark('loaded');
    const title = page.locator('text=/^host-clone-1$/').first(); await title.waitFor({ timeout: 20000 }); const tb = await title.boundingBox();
    await glide(page, tb.x + 120, tb.y + tb.height + 80, 600); mark('modal'); await page.waitForTimeout(4000);
    const start = await api('POST', '/server/script/execute', { host_name: 'host-clone-1', device_id: 'host', script_name: 'goto', parameters: '--userinterface youtube-web --node video_player' });
    console.log('goto started', start.task_id); mark('goto-start');
    let result = null;
    for (let i = 0; i < 60; i++) {
      await page.waitForTimeout(5000);
      if (i % 6 === 0) await page.mouse.move(900 + (i % 12) * 20, 600, { steps: 10 });
      const st = await api('GET', `/server/script/status/${start.task_id}`); const task = st.task || {};
      if (task.completed_at) { result = task.result; break; }
    }
    mark('goto-done'); await page.waitForTimeout(3000); mark('end');
    await page.screenshot({ path: path.join(OUT, 'goto-final.png') });
    return { task_id: start.task_id, result };
  });
}

// ---- 3. report stills for the goto run
async function report(reportUrl) {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW }); const page = await ctx.newPage();
  await page.goto(reportUrl, { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(4000);
  await page.evaluate(() => document.querySelectorAll('details').forEach(d => d.open = true)); await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(OUT, 'report-goto-full.png'), fullPage: true });
  // expand the Test Mosaic section
  const mosaic = page.locator('text=/Test Mosaic/').first();
  if (await mosaic.count()) { await mosaic.click().catch(() => {}); await page.waitForTimeout(2500); await page.screenshot({ path: path.join(OUT, 'report-goto-mosaic.png'), fullPage: true }); }
  const h = await page.evaluate(() => document.body.scrollHeight); console.log('report captured, height', h);
  await browser.close();
}

(async () => {
  if (mode === 'editor' || mode === 'all') await editor();
  let extra = null;
  if (mode === 'goto' || mode === 'all') extra = await gotoLive();
  if (mode === 'report' || mode === 'all') {
    let rep = process.argv[3];
    if (!rep && extra && extra.result) rep = extra.result.report_url;
    if (!rep && fs.existsSync(path.join(OUT, 'goto-live.marks.json'))) rep = (JSON.parse(fs.readFileSync(path.join(OUT, 'goto-live.marks.json'), 'utf8')).result || {}).report_url;
    if (rep) await report(rep); else console.log('no report url');
  }
})();
