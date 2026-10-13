// Assets for video 7 (zap detection): rpitest, stb4 on vpt-pi3, from the Device page with no script.
// Needs a local frontend pointed at rpitest (frontend/.env.local: VITE_SERVER_URL=https://rpitest.angelstreet.io)
// on PROMO_BASE (default http://localhost:5074). rpitest's CORS only allows :5073, so the browser relays
// rpitest API calls through Playwright and adds the CORS headers itself.
// Usage: node zap_capture.js
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path'); const https = require('https');
const DIR = __dirname; const OUT = path.join(DIR, 'raw7'); fs.mkdirSync(OUT, { recursive: true });
const TOKEN = fs.readFileSync(path.join(DIR, '.token'), 'utf8').trim();
const TEAM = '7fdeb4bb-3639-4ec3-959f-b54769a219ce';
if (!process.env.PROMO_SERVER) throw new Error('PROMO_SERVER is required (public URL of the server, e.g. https://<server>.angelstreet.io)'); const SERVER = process.env.PROMO_SERVER; const BASE = process.env.PROMO_BASE || 'http://localhost:5074';
const VIEW = { width: 1920, height: 1080 };
const url = (p) => `${BASE}${p}${p.includes('?') ? '&' : '?'}auto_signed=${TOKEN}`;
const CURSOR = fs.readFileSync(path.join(DIR, 'capture.js'), 'utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];
const HOST = 'vpt-pi3', DEVICE = 'device4', CARD = 'stb4 - vpt-pi3';

function api(method, p, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(`${SERVER}${p}`); u.searchParams.set('team_id', TEAM);
    const data = body ? JSON.stringify(body) : null;
    const headers = { 'User-Agent': 'Mozilla/5.0', 'X-Auto-Sign': TOKEN };
    if (data) { headers['Content-Type'] = 'application/json'; headers['Content-Length'] = Buffer.byteLength(data); }
    const req = https.request(u, { method, headers }, res => { let s = ''; res.on('data', d => s += d); res.on('end', () => { try { resolve(JSON.parse(s)); } catch (e) { resolve({ raw: s.slice(0, 200) }); } }); });
    req.on('error', reject); if (data) req.write(data); req.end();
  });
}
// A crashed or finished walk leaves the manual control lock behind (its heartbeat stops): release ours.
async function releaseOurLock() {
  const l = await api('GET', '/server/control/lockedDevices'); const lock = (l.locked_devices || {})[`${HOST}:${DEVICE}`];
  if (lock && lock.owner_user_name === 'Auto Signed') {
    const r = await api('POST', '/server/control/releaseControl', { host_name: HOST, device_id: DEVICE, session_id: lock.owner_session_id });
    console.log('released control', r.success);
  }
}
async function glide(page, x, y, pause = 500) { await page.mouse.move(x, y, { steps: 28 }); await page.waitForTimeout(pause); await page.mouse.click(x, y); }
async function center(loc) { const b = await loc.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; }

// node zap_capture.js key CHANNEL_DOWN CHANNEL_DOWN : move the box off camera (no recording), then release
async function pressKeys(keys) {
  const browser = await chromium.launch({ headless: true }); const ctx = await browser.newContext({ viewport: VIEW });
  await relay(ctx); const page = await ctx.newPage();
  try {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2000);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 });
    const title = page.locator(`text=/^${CARD}$/`).first(); await title.waitFor({ timeout: 90000 }); await page.waitForTimeout(2000);
    const tb = await title.boundingBox(); const take = page.getByRole('button', { name: /take control/i }).first();
    for (let i = 0; i < 4 && !(await take.isVisible().catch(() => false)); i++) { await page.mouse.click(tb.x + 120, tb.y + tb.height + 80); await page.waitForTimeout(3000); }
    await take.click(); await page.locator('[title$="CHANNEL_UP"]').first().waitFor({ timeout: 30000 }); await page.waitForTimeout(2000);
    for (const k of keys) { await page.locator(`[title$=" - ${k}"]`).first().click(); console.log('pressed', k); await page.waitForTimeout(6000); }
    await page.screenshot({ path: path.join(OUT, 'after-keys.png') });
  } catch (e) { console.log('ERROR', e.message.slice(0, 160)); }
  await releaseOurLock().catch(() => {}); await browser.close();
}
// the shared relay (promo_lib): CORS for this capture's local origin, storage proxy, ranged media
const relay = ctx => require('./promo_lib')(OUT).relay(ctx, { base: BASE });

// node zap_capture.js report <zap report url> : the zap report walk as its own clip (zapreport.webm)
async function reportWalk(reportUrl) {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW, recordVideo: { dir: path.join(OUT, 'video-zapreport'), size: VIEW } });
  await ctx.addInitScript(CURSOR); const page = await ctx.newPage();
  const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  const hover = async (re, dx, dy, wait) => { const l = page.getByText(re).first(); const b = await l.boundingBox({ timeout: 3000 }).catch(() => null); if (b) { await page.mouse.move(b.x + dx, b.y + dy, { steps: 24 }); await page.waitForTimeout(wait); } return !!b; };
  try {
    await page.goto(reportUrl, { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(1500, 60);
    await page.waitForFunction(() => [...document.images].every(i => i.complete && i.naturalWidth > 0), null, { timeout: 60000 }).catch(() => console.log('some images did not load'));
    await page.waitForTimeout(2500); mark('report');
    await page.screenshot({ path: path.join(OUT, 'zap-report-top.png') });
    for (const re of [/^At key press$/, /^Before transition$/, /^Freeze start$/, /^Freeze end$/, /^After \(new content\)$/]) await hover(re, 150, 110, 1500);
    mark('frames');
    await hover(/^Total zap time$/, 280, 10, 3500); mark('total');
    await hover(/^Freeze duration$/, 280, 10, 2500);
    await hover(/^Transition type$/, 280, 10, 2000);
    await hover(/^Detection$/, 280, 10, 3000); mark('details');
    await page.screenshot({ path: path.join(OUT, 'zap-report.png') }); await page.waitForTimeout(1500); mark('end');
  } catch (e) { console.log('ERROR', e.message.slice(0, 200)); }
  const vid = page.video(); await ctx.close(); fs.copyFileSync(await vid.path(), path.join(OUT, 'zapreport.webm'));
  fs.writeFileSync(path.join(OUT, 'zapreport.marks.json'), JSON.stringify({ marks, report_url: reportUrl }, null, 1)); await browser.close();
  console.log('clip zapreport', marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
}

(async () => {
  if (process.argv[2] === 'key') return pressKeys(process.argv.slice(3));
  if (process.argv[2] === 'report') return reportWalk(process.argv[3]);
  const l0 = await api('GET', '/server/control/lockedDevices');
  if ((l0.locked_devices || {})[`${HOST}:${DEVICE}`]) { console.log('device is locked by someone else, stop'); return; }
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW, ignoreHTTPSErrors: true, recordVideo: { dir: path.join(OUT, 'video-zap'), size: VIEW } });
  await ctx.addInitScript(CURSOR);
  await relay(ctx);
  const page = await ctx.newPage(); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  let extra = {};
  try {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2000);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 }); await page.mouse.move(960, 700);
    await page.locator(`text=/^${CARD}$/`).first().waitFor({ timeout: 90000 }); await page.waitForTimeout(3000);
    // no Targets filter (a click after closing that select does not open the modal): the build starts
    // once the modal is open, so the grid with the other boxes is never in the video
    mark('filtered');
    const title = page.locator(`text=/^${CARD}$/`).first(); const tb = await title.boundingBox();
    const take = page.getByRole('button', { name: /take control/i }).first();
    await glide(page, tb.x + 120, tb.y + tb.height + 80, 700);
    // the first click after closing the Targets select can be swallowed: click again if the modal is not up
    for (let i = 0; i < 3 && !(await take.isVisible().catch(() => false)); i++) { await page.waitForTimeout(2500); if (!(await take.isVisible().catch(() => false))) await page.mouse.click(tb.x + 120, tb.y + tb.height + 80); }
    await take.waitFor({ timeout: 30000 }); await page.waitForTimeout(4000); mark('modal');
    await glide(page, ...(await center(take)), 600);
    await page.locator('[title$="CHANNEL_UP"]').first().waitFor({ timeout: 30000 }); await page.waitForTimeout(3000); mark('control');
    const mon = page.getByRole('button', { name: /^monitoring$/i }).last(); await glide(page, ...(await center(mon)), 600);
    await page.mouse.move(900, 500, { steps: 20 }); await page.waitForTimeout(6000); mark('monitoring');
    await page.screenshot({ path: path.join(OUT, 'modal-monitoring.png') });
    const chup = page.locator('[title$="CHANNEL_UP"]').first(); await glide(page, ...(await center(chup)), 900); mark('chup');
    const card = page.locator('text=/ZAP\\s*→/').last(); await card.waitFor({ timeout: 60000 }); await page.waitForTimeout(1500); mark('zap-card');
    const cb = await card.boundingBox(); await page.mouse.move(cb.x + 60, cb.y + 40, { steps: 25 }); await page.waitForTimeout(4000); mark('zap-read');
    await page.screenshot({ path: path.join(OUT, 'modal-zap-card.png') });
    const link = page.locator('a:has-text("Report")').last(); const href = await link.getAttribute('href'); extra.zap_report_url = href;
    await link.evaluate(a => { a.target = '_self'; });   // a new tab is not recorded; same page in this tab
    await releaseOurLock();                               // we leave the modal: do not leave the box locked
    await glide(page, ...(await center(link)), 1000); mark('link');
    await page.waitForLoadState('load').catch(() => {}); await page.mouse.move(1500, 60, { steps: 20 }); await page.waitForTimeout(3500); mark('report');
    await page.screenshot({ path: path.join(OUT, 'zap-report-top.png') });
    const frames = page.locator('text=/At key press/').first(); const fb = await frames.boundingBox().catch(() => null);
    if (fb) { await page.mouse.move(fb.x + 150, fb.y + 120, { steps: 25 }); await page.waitForTimeout(2000); }
    for (const label of ['Before transition', 'Freeze start', 'Freeze end', 'After (new content)']) {
      const l = page.locator(`text=/^${label.replace(/[()]/g, '\\$&')}$/`).first(); const b = await l.boundingBox().catch(() => null);
      if (b) { await page.mouse.move(b.x + 150, b.y + 120, { steps: 22 }); await page.waitForTimeout(1300); }
    }
    mark('frames');
    const total = page.locator('text=/^Total zap time$/').first(); const tzb = await total.boundingBox().catch(() => null);
    if (tzb) { await page.mouse.move(tzb.x + 260, tzb.y + 10, { steps: 25 }); await page.waitForTimeout(3500); }
    mark('total');
    const fr = page.locator('text=/^Freeze duration$/').first(); const frb = await fr.boundingBox().catch(() => null);
    if (frb) { await page.mouse.move(frb.x + 260, frb.y + 10, { steps: 20 }); await page.waitForTimeout(2500); }
    const det = page.locator('text=/^Detection$/').first(); const db = await det.boundingBox().catch(() => null);
    if (db) { await page.mouse.move(db.x + 260, db.y + 10, { steps: 20 }); await page.waitForTimeout(3000); }
    mark('details'); await page.screenshot({ path: path.join(OUT, 'zap-report.png') });
    await page.waitForTimeout(1500); mark('end');
  } catch (e) { console.log('ERROR', e.message.slice(0, 200)); await page.screenshot({ path: path.join(OUT, 'zap-error.png') }).catch(() => {}); }
  await releaseOurLock().catch(() => {});
  const vid = page.video(); await ctx.close(); fs.copyFileSync(await vid.path(), path.join(OUT, 'zap.webm'));
  fs.writeFileSync(path.join(OUT, 'zap.marks.json'), JSON.stringify({ marks, ...extra }, null, 1)); await browser.close();
  console.log('clip zap', marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
