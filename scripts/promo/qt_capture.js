// Assets for the QuickTest video: a test built in a few clicks (CH+, detect motion) on a set-top
// box, run, passed, then its report. rpitest, stb4 on vpt-pi1, interface from env QT_UI.
// Needs a local frontend pointed at rpitest (frontend/.env.local: VITE_SERVER_URL=https://rpitest.angelstreet.io)
// on PROMO_BASE (default http://localhost:5075), like zap_capture.js: rpitest's CORS only allows :5073, so the
// browser relays rpitest API calls and adds the CORS headers itself. The test is run, not saved.
// Usage: node qt_capture.js        -> raw10/qt.webm + qt.marks.json
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path'); const https = require('https');
const DIR = __dirname; const OUT = path.join(DIR, 'raw10'); fs.mkdirSync(OUT, { recursive: true });
const TOKEN = fs.readFileSync(path.join(DIR, '.token'), 'utf8').trim();
const TEAM = '7fdeb4bb-3639-4ec3-959f-b54769a219ce';
if (!process.env.PROMO_SERVER) throw new Error('PROMO_SERVER is required (public URL of the server, e.g. https://<server>.angelstreet.io)'); const SERVER = process.env.PROMO_SERVER; const BASE = process.env.PROMO_BASE || 'http://localhost:5075';
const VIEW = { width: 1920, height: 1080 };
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
const url = (p) => `${BASE}${p}${p.includes('?') ? '&' : '?'}auto_signed=${TOKEN}`;
const CURSOR = fs.readFileSync(path.join(DIR, 'capture.js'), 'utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];
const TARGET = /^stb4 \(vpt-pi1\)/, IFACE = process.env.QT_UI, HOST = 'vpt-pi1', DEVICE = 'device4';
const NAME = process.env.QT_NAME || 'Zap and check';

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
// A crashed walk leaves the manual control lock behind: release ours.
async function releaseOurLock() {
  const l = await api('GET', '/server/control/lockedDevices'); const lock = (l.locked_devices || {})[`${HOST}:${DEVICE}`];
  if (lock && lock.owner_user_name === 'Auto Signed') {
    const r = await api('POST', '/server/control/releaseControl', { host_name: HOST, device_id: DEVICE, session_id: lock.owner_session_id });
    console.log('released control', r.success);
  }
}
// the shared relay (promo_lib): CORS for this capture's local origin, storage proxy, ranged media
const relay = ctx => require('./promo_lib')(OUT).relay(ctx, { base: BASE });
async function glide(page, x, y, pause = 500) { await page.mouse.move(x, y, { steps: 26 }); await page.waitForTimeout(pause); await page.mouse.click(x, y); }
async function center(loc) { const b = await loc.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; }
// open a MUI select at (x, y) and pick an option, the cursor visibly moving to it
async function choose(page, x, y, option) {
  await glide(page, x, y, 450); await page.waitForTimeout(700);
  const o = page.getByRole('option', { name: option, exact: typeof option === 'string' }).first();
  await o.scrollIntoViewIfNeeded(); await page.waitForTimeout(250);
  await glide(page, ...(await center(o)), 450); await page.waitForTimeout(700);
}
// the select sitting under a field label, in the last step card
async function selectUnder(page, label) {
  const l = page.locator('label', { hasText: new RegExp(`^${label}$`) }).last(); const b = await l.boundingBox();
  return [b.x + 90, b.y + b.height / 2 + 12];
}

(async () => {
  const l0 = await api('GET', '/server/control/lockedDevices');
  if ((l0.locked_devices || {})[`${HOST}:${DEVICE}`]) { console.log('device is locked, stop'); return; }
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW, userAgent: UA, recordVideo: { dir: path.join(OUT, 'video-qt'), size: VIEW } });
  await ctx.addInitScript(CURSOR); await relay(ctx);
  const page = await ctx.newPage(); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  const extra = {};
  try {
    await page.goto(url('/builder/quick-test'), { waitUntil: 'load', timeout: 180000 }); await page.mouse.move(1200, 500);
    await page.getByRole('button', { name: /^Loop$/ }).waitFor({ timeout: 90000 }); await page.waitForTimeout(6000); mark('page');
    // 1. the box: target, interface, take control
    await choose(page, 750, 88, TARGET); await page.waitForTimeout(1200);
    await choose(page, 900, 88, IFACE); await page.waitForTimeout(1500);
    await glide(page, ...(await center(page.getByRole('button', { name: /Control/ }).first())), 500);
    await page.getByRole('button', { name: /Release/ }).first().waitFor({ timeout: 30000 }); await page.waitForTimeout(9000); mark('control');
    // 2. name it, two steps (the box is already on live: no go-to step)
    await glide(page, 900, 152, 400); await page.keyboard.type(NAME, { delay: 70 }); await page.waitForTimeout(800); mark('named');
    await glide(page, ...(await center(page.getByRole('button', { name: /^Action$/ }).last())), 400); await page.waitForTimeout(1200);
    await choose(page, ...(await selectUnder(page, 'Action')), 'CHANNEL_UP'); mark('action');
    await glide(page, ...(await center(page.getByRole('button', { name: /^Verification$/ }).last())), 400); await page.waitForTimeout(1500);
    await choose(page, ...(await selectUnder(page, 'Verification')), 'Detect Motion'); mark('verification');
    await page.mouse.move(1200, 650, { steps: 20 }); await page.waitForTimeout(2500); mark('built');
    await page.screenshot({ path: path.join(OUT, 'qt-built.png') });
    // 3. bigger picture for the run: the HDMI panel's expand button
    // the expand icon is the header's last button (the chevron before it only collapses the panel)
    const hdr = page.locator('text=HDMI').first().locator('xpath=ancestor::*[.//button][1]');
    await glide(page, ...(await center(hdr.locator('button').last())), 500); await page.waitForTimeout(3500);
    await page.screenshot({ path: path.join(OUT, 'qt-expanded.png') }); mark('expanded');
    // 4. run
    await glide(page, ...(await center(page.getByRole('button', { name: /^Run$/ }))), 600); mark('run');
    await page.getByText(/TEST (PASSED|FAILED)/).first().waitFor({ timeout: 120000 }); mark('passed');
    extra.result = await page.getByText(/TEST (PASSED|FAILED)/).first().innerText();
    await page.waitForTimeout(1500); await page.screenshot({ path: path.join(OUT, 'qt-passed.png') });
    const steps = page.getByText(/STEP \d: .* SUCCESS/);
    for (let i = (await steps.count()) - 1; i >= 0; i--) { const b = await steps.nth(i).boundingBox().catch(() => null); if (b) { await page.mouse.move(b.x + 120, b.y + b.height / 2, { steps: 18 }); await page.waitForTimeout(1300); } }
    await page.waitForTimeout(1500); mark('held');
    // 5. the report, in this tab
    const link = page.locator('a', { hasText: 'Report' }).first(); extra.report_url = (await link.getAttribute('href')).split('?')[0];
    await link.evaluate(a => { a.target = '_self'; });
    await releaseOurLock();
    await glide(page, ...(await center(link)), 800); mark('link');
    await page.waitForLoadState('load').catch(() => {}); await page.mouse.move(1500, 300, { steps: 15 });
    await page.waitForFunction(() => [...document.images].every(i => i.complete && i.naturalWidth > 0), null, { timeout: 45000 }).catch(() => console.log('some report images did not load'));
    await page.waitForTimeout(2500); mark('report');
    await page.screenshot({ path: path.join(OUT, 'qt-report.png') });
    for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, 140); await page.waitForTimeout(450); }
    await page.waitForTimeout(3000); mark('report-steps');
    await page.screenshot({ path: path.join(OUT, 'qt-report-steps.png') });
    await page.waitForTimeout(1500); mark('end');
  } catch (e) { console.log('ERROR', e.message.replace(/auto_signed=\w+/g, 'auto_signed=X').slice(0, 220)); await page.screenshot({ path: path.join(OUT, 'qt-error.png') }).catch(() => {}); }
  await releaseOurLock().catch(() => {});
  const vid = page.video(); await ctx.close(); fs.copyFileSync(await vid.path(), path.join(OUT, 'qt.webm'));
  fs.writeFileSync(path.join(OUT, 'qt.marks.json'), JSON.stringify({ marks, ...extra }, null, 1)); await browser.close();
  console.log('clip qt', marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '), JSON.stringify(extra));
})();
