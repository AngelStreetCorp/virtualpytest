// Assets for video 5 (KPI), host-clone-1 + youtube-web, straight against prod.
// Usage: node kpi_capture.js [editor|goto|kpireport|testreport <url>|report <url>|all]
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path'); const https = require('https');
const DIR = __dirname; const OUT = path.join(DIR, 'raw5'); fs.mkdirSync(OUT, { recursive: true });
const TOKEN = fs.readFileSync(path.join(DIR, '.token'), 'utf8').trim();
const TEAM = '7fdeb4bb-3639-4ec3-959f-b54769a219ce';
const SERVER = 'https://virtualpytest.angelstreet.io'; const BASE = process.env.PROMO_BASE || SERVER;
const VIEW = { width: 1920, height: 1080 }; const mode = process.argv[2] || 'all';
const url = (p) => `${BASE}${p}${p.includes('?') ? '&' : '?'}auto_signed=${TOKEN}`;
const CURSOR = fs.readFileSync(path.join(DIR, 'capture.js'), 'utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];
const EDGE = 'edge-home-to-search_results';

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
async function dragNode(page, label, dx, dy) {
  const n = page.locator(`.react-flow__node:has-text("${label}")`).first();
  const bb = await n.boundingBox(); const x = bb.x + bb.width / 2, y = bb.y + 28;
  await page.mouse.move(x, y, { steps: 20 }); await page.mouse.down(); await page.waitForTimeout(150);
  await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 18 }); await page.mouse.move(x + dx, y + dy, { steps: 18 });
  await page.waitForTimeout(150); await page.mouse.up(); await page.waitForTimeout(500);
}
// The home -> search_results path is routed behind the home node, so a real click cannot reach it:
// glide the cursor to home's right connector, then select the edge through React Flow's own click handler.
async function selectEdge(page, edgeId) {
  const home = await page.locator('.react-flow__node:has-text("home")').first().boundingBox();
  await page.mouse.move(home.x + home.width + 6, home.y + home.height / 2 - 8, { steps: 30 }); await page.waitForTimeout(500);
  const ok = await page.evaluate((id) => {
    const g = document.querySelector(`[data-testid="rf__edge-${id}"]`) || Array.from(document.querySelectorAll('.react-flow__edge')).find(e => (e.getAttribute('aria-label') || '').includes('home to search_results'));
    if (!g) return false;
    const p = g.querySelector('path.react-flow__edge-interaction') || g.querySelector('path');
    p.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    return true;
  }, edgeId);
  return { found: ok };
}
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
  const page = await ctx.newPage(); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  let extra = {};
  try { extra = (await fn(page, mark)) || {}; } catch (e) { console.log('clip', name, 'ERROR', e.message); await page.screenshot({ path: path.join(OUT, `${name}-error.png`) }).catch(() => {}); }
  const vid = page.video(); await ctx.close(); fs.copyFileSync(await vid.path(), path.join(OUT, `${name}.webm`));
  fs.writeFileSync(path.join(OUT, `${name}.marks.json`), JSON.stringify({ marks, ...extra }, null, 1)); await browser.close();
  console.log('clip', name, marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
  return extra;
}
async function openEditor(page, mark) {
  await page.goto(url('/'), { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(2500);
  await page.goto(url('/navigation-editor/youtube-web'), { waitUntil: 'load', timeout: 60000 }); await page.mouse.move(960, 600); await page.waitForTimeout(9000);
  await closeToast(page); mark('loaded');
  const fit = page.locator('button[title="fit view"]').first(); const fb = await fit.boundingBox(); await glide(page, fb.x + fb.width / 2, fb.y + fb.height / 2); await page.waitForTimeout(1500); mark('tidy');
  return fb;
}
async function takeControl(page, mark) {
  const sel = page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first();
  const sb = await sel.boundingBox(); await glide(page, sb.x + sb.width / 2, sb.y + sb.height / 2); await page.waitForTimeout(900);
  const opt = page.locator('[role="option"]').filter({ hasText: /host-clone-1/ }).first(); const ob = await opt.boundingBox(); await glide(page, ob.x + ob.width / 2, ob.y + ob.height / 2); await page.waitForTimeout(1500); mark('target');
  const ctl = page.getByRole('button', { name: /^control$/i }).first(); const cb = await ctl.boundingBox(); await glide(page, cb.x + cb.width / 2, cb.y + cb.height / 2, 600); mark('control');
  for (let i = 0; i < 11; i++) { await page.waitForTimeout(5000); await page.mouse.move(700 + i * 15, 500, { steps: 8 }); }
  mark('stream');
}
async function releaseControl(page) { const rel = page.getByRole('button', { name: /release/i }).first(); if (await rel.count()) { await rel.click().catch(() => {}); await page.waitForTimeout(1000); } }

// ---- 1. editor: tidy, take control, select the edge, open the edit dialog, show the KPI section
async function editor() {
  await record('editor-kpi', async (page, mark) => {
    await openEditor(page, mark);
    await takeControl(page, mark);
    const mp = await selectEdge(page, EDGE); if (!mp.found) throw new Error('edge not found');
    await page.waitForTimeout(1500); mark('edge');
    await page.screenshot({ path: path.join(OUT, 'editor-edge.png') });
    const edit = page.getByRole('button', { name: /^edit$/i }).first(); await edit.waitFor({ timeout: 10000 }); const eb = await edit.boundingBox();
    await glide(page, eb.x + eb.width / 2, eb.y + eb.height / 2, 600); await page.waitForTimeout(2500); mark('dialog');
    await page.screenshot({ path: path.join(OUT, 'editor-dialog.png') });
    const kpi = page.locator('text=/KPI Measurement/').first(); await kpi.waitFor({ timeout: 10000 });
    await kpi.scrollIntoViewIfNeeded(); await page.waitForTimeout(500);
    const kb = await kpi.boundingBox(); await page.mouse.move(kb.x + 40, kb.y + 10, { steps: 25 }); await page.waitForTimeout(400);
    await page.mouse.wheel(0, 260); await page.waitForTimeout(1800); mark('kpi');
    await page.screenshot({ path: path.join(OUT, 'editor-dialog-kpi.png') });
    await page.mouse.move(kb.x + 200, kb.y + 120, { steps: 25 }); await page.waitForTimeout(2500); mark('kpi-end');
    await page.keyboard.press('Escape'); await page.waitForTimeout(800);
    await releaseControl(page); mark('end');
  });
}

// ---- 2. goto live: device modal open, goto search_results over the API
async function gotoLive() {
  return record('goto-kpi', async (page, mark) => {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(2500);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 60000 }); await page.mouse.move(960, 700); await page.waitForTimeout(8000); mark('loaded');
    const title = page.locator('text=/^host-clone-1$/').first(); await title.waitFor({ timeout: 20000 }); const tb = await title.boundingBox();
    await glide(page, tb.x + 120, tb.y + tb.height + 80, 600); mark('modal'); await page.waitForTimeout(4000);
    const start = await api('POST', '/server/script/execute', { host_name: 'host-clone-1', device_id: 'host', script_name: 'goto', parameters: '--userinterface youtube-web --node search_results' });
    console.log('goto started', start.task_id, start.error || ''); mark('goto-start');
    let result = null;
    for (let i = 0; i < 160; i++) {
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

// ---- 3. back in the editor: the edge now carries its KPI; hover the chip, then walk the KPI report
async function kpiReport() {
  return record('kpi-report', async (page, mark) => {
    await openEditor(page, mark);
    const mp = await selectEdge(page, EDGE); if (!mp.found) throw new Error('edge not found');
    await page.waitForTimeout(1800); mark('edge');
    await page.screenshot({ path: path.join(OUT, 'editor-edge-kpi.png') });
    const chip = page.locator('a[href*="kpi_measurement"]').first(); let href = null;
    if (await chip.count()) { href = await chip.getAttribute('href'); const cb = await chip.boundingBox(); await page.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2, { steps: 25 }); await page.waitForTimeout(1200); mark('chip'); }
    if (!href) {
      const rows = await api('GET', '/server/execution-results/getAllExecutionResults?limit=30');
      const list = Array.isArray(rows) ? rows : (rows.results || rows.execution_results || rows.data || []);
      href = (list.find(r => r.edge_id === EDGE && r.kpi_report_url) || {}).kpi_report_url; console.log('chip missing, using latest report url');
    }
    await page.goto(href, { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(3500); mark('report');
    await page.screenshot({ path: path.join(OUT, 'kpi-report-top.png') });
    await page.mouse.move(1500, 700, { steps: 20 }); await page.waitForTimeout(2500);
    const slow = async (px, n, pause = 900) => { for (let i = 0; i < n; i++) { await page.mouse.wheel(0, px); await page.waitForTimeout(pause); } };
    await slow(150, 3); await page.waitForTimeout(2500); mark('frames');          // the six frames row
    // the scan mosaic strip: click it (the report's own lightbox opens), 5 s on it, close with its ✕
    const strip = page.locator('details.scan-mosaic a img').first();
    if (await strip.count()) {
      const sb = await strip.boundingBox();
      await glide(page, sb.x + Math.min(sb.width / 2, 700), sb.y + Math.min(sb.height / 2, 120), 900);  // glide clicks
      mark('mosaic');
      await page.mouse.move(960, 600, { steps: 15 }); await page.waitForTimeout(5000); mark('mosaic-close');
      const x = page.locator('#modal .close'); const xb = await x.boundingBox();
      if (xb) await glide(page, xb.x + xb.width / 2, xb.y + xb.height / 2, 500); else await page.keyboard.press('Escape');
      await page.waitForTimeout(1200); mark('mosaic-back');
    }
    const verif = page.locator('details.verification-evidence > summary').first();
    if (await verif.count()) {
      for (let i = 0; i < 30; i++) { const vb = await verif.boundingBox(); if (vb && vb.y < 420) break; await page.mouse.wheel(0, 150); await page.waitForTimeout(700); }
      const vb = await verif.boundingBox(); await page.mouse.move(vb.x + 60, vb.y + vb.height / 2, { steps: 25 }); await page.waitForTimeout(1500); mark('verification');
      await slow(120, 5, 1000); await page.waitForTimeout(3500); mark('reference');   // searched text, source OCR crop, score
    }
    await page.screenshot({ path: path.join(OUT, 'kpi-report-verification.png') });
    await page.waitForTimeout(1500); mark('end');
    // full-page capture re-lays out the page (a glitch frame in the video): only after the walk
    await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({ path: path.join(OUT, 'kpi-report-full.png'), fullPage: true });
    return { kpi_report_url: href };
  });
}

// ---- 4. test report walk: scroll to the Test Mosaic, expand it
async function testReport(reportUrl) {
  return record('test-report', async (page, mark) => {
    await page.goto(reportUrl, { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(3500); mark('report');
    await page.mouse.move(1500, 700, { steps: 20 }); await page.waitForTimeout(2000);
    const mosaic = page.locator('text=/Test Mosaic/').first(); await mosaic.waitFor({ timeout: 10000 });
    for (let i = 0; i < 12; i++) { const mb = await mosaic.boundingBox(); if (mb && mb.y < 700) break; await page.mouse.wheel(0, 150); await page.waitForTimeout(700); }
    const mb = await mosaic.boundingBox(); await page.mouse.move(mb.x + 40, mb.y + mb.height / 2, { steps: 25 }); await page.waitForTimeout(1200); mark('mosaic-header');
    await page.mouse.click(mb.x + 40, mb.y + mb.height / 2); await page.waitForTimeout(2500); mark('mosaic-open');
    for (let i = 0; i < 4; i++) { await page.mouse.wheel(0, 120); await page.waitForTimeout(900); }
    await page.waitForTimeout(3500); mark('end');
    await page.screenshot({ path: path.join(OUT, 'report-goto-mosaic-open.png') });
  });
}

// ---- 5. test report stills (Test Mosaic)
async function report(reportUrl) {
  const browser = await chromium.launch({ headless: true }); const ctx = await browser.newContext({ viewport: VIEW }); const page = await ctx.newPage();
  await page.goto(reportUrl, { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(4000);
  await page.evaluate(() => document.querySelectorAll('details').forEach(d => d.open = true)); await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(OUT, 'report-goto-full.png'), fullPage: true });
  const mosaic = page.locator('text=/Test Mosaic/').first();
  if (await mosaic.count()) { await mosaic.click().catch(() => {}); await page.waitForTimeout(2500); await page.screenshot({ path: path.join(OUT, 'report-goto-mosaic.png'), fullPage: true }); }
  console.log('report captured'); await browser.close();
}

(async () => {
  if (mode === 'editor' || mode === 'all') await editor();
  let extra = null;
  if (mode === 'goto' || mode === 'all') extra = await gotoLive();
  if (mode === 'kpireport' || mode === 'all') await kpiReport();
  if (mode === 'testreport' || mode === 'report' || mode === 'all') {
    let rep = process.argv[3];
    if (!rep && extra && extra.result) rep = extra.result.report_url;
    if (!rep && fs.existsSync(path.join(OUT, 'goto-kpi.marks.json'))) rep = (JSON.parse(fs.readFileSync(path.join(OUT, 'goto-kpi.marks.json'), 'utf8')).result || {}).report_url;
    if (rep && mode !== 'report') await testReport(rep);
    if (rep) await report(rep); else console.log('no report url');
  }
})();
