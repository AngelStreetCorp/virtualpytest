// Assets for video 9 (24 h monitoring): rpitest heatmap -> a device's last 24 h -> the incident.
// Needs a local frontend pointed at rpitest (frontend/.env.local: VITE_SERVER_URL=https://rpitest.angelstreet.io)
// on PROMO_BASE (default http://localhost:5074), like zap_capture.js. The capture browser relays rpitest API
// calls (rpitest's CORS only allows :5073) and strips the storage bucket's Cross-Origin-Resource-Policy
// header, which otherwise blocks incident frames on any origin but the prod domain.
// Nothing is driven: the page only reads what monitoring recorded.
// Usage: node mon_capture.js [HH:MM:SS incident start, local time]   (default: MON_INCIDENT or 22:55:18)
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const DIR = __dirname; const OUT = path.join(DIR, 'raw9'); fs.mkdirSync(OUT, { recursive: true });
const TOKEN = fs.readFileSync(path.join(DIR, '.token'), 'utf8').trim();
const BASE = process.env.PROMO_BASE || 'http://localhost:5074';
const VIEW = { width: 1920, height: 1080 };
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
const url = (p) => `${BASE}${p}${p.includes('?') ? '&' : '?'}auto_signed=${TOKEN}`;
const CURSOR = fs.readFileSync(path.join(DIR, 'capture.js'), 'utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];
// The incident: stb3 on vpt-pi1 stuck on a channel banner. Its tile sits top right of the 7-device mosaic.
const INCIDENT = process.argv[2] || process.env.MON_INCIDENT || '22:55:18';
const TILE = (process.env.MON_TILE || '1195,248').split(',').map(Number); const DEVICE = process.env.MON_DEVICE || 'stb3';
const secs = (hms) => { const [h, m, s = 0] = hms.split(':').map(Number); return h * 3600 + m * 60 + s; };
const hms = (t) => [Math.floor(t / 3600) % 24, Math.floor(t / 60) % 60, t % 60].map(n => String(n).padStart(2, '0')).join(':');
const nowSecs = () => { const d = new Date(); return d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds(); };
const ago = (t) => ((nowSecs() - t) % 86400 + 86400) % 86400;   // seconds between t (clock time) and now

// the shared relay (promo_lib): CORS for this capture's local origin, storage proxy, ranged media
const relay = ctx => require('./promo_lib')(OUT).relay(ctx, { base: BASE });
async function glide(page, x, y, pause = 500) { await page.mouse.move(x, y, { steps: 28 }); await page.waitForTimeout(pause); await page.mouse.click(x, y); }
async function center(loc) { const b = await loc.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; }
// Drag a MUI slider thumb to x, slowly, so the scrub is visible.
async function drag(page, thumb, x, steps = 60, ms = 70) {
  const [x0, y0] = await center(thumb);
  await page.mouse.move(x0, y0, { steps: 20 }); await page.waitForTimeout(400); await page.mouse.down();
  for (let i = 1; i <= steps; i++) { await page.mouse.move(x0 + (x - x0) * i / steps, y0); await page.waitForTimeout(ms); }
  await page.mouse.up();
}

(async () => {
  const t0s = secs(INCIDENT);
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW, userAgent: UA, recordVideo: { dir: path.join(OUT, 'video-mon'), size: VIEW } });
  await ctx.addInitScript(CURSOR); await relay(ctx);
  const page = await ctx.newPage(); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  page.on('console', m => { const t = m.text(); if (/Seek time:/.test(t)) console.log('  ', t.trim()); });
  try {
    // 1. Heatmap, now; then scrub the day back to the minute after the freeze started
    await page.goto(url('/monitoring/heatmap'), { waitUntil: 'load', timeout: 180000 }); await page.mouse.move(1700, 400);
    await page.getByText('24h Heatmap').first().waitFor({ timeout: 90000 }); await page.waitForTimeout(10000);
    // the latest minute can hold a tile that is not capturing (NOT FOUND): start from the evening instead,
    // before the clip begins, and scrub forward to the freeze
    await page.getByText(process.env.MON_FROM || '18h', { exact: true }).first().click(); await page.mouse.move(1700, 400); await page.waitForTimeout(7000); mark('heatmap');
    await page.screenshot({ path: path.join(OUT, 'heatmap-now.png') });
    const rail = await page.locator('.MuiSlider-rail').first().boundingBox();
    const back = Math.round(ago(t0s + 60) / 60);   // frames are one per minute, the latest is index 1439
    const hx = rail.x + rail.width * (1439 - back) / 1439;
    mark('scrub'); await drag(page, page.locator('.MuiSlider-thumb').first(), hx, 70, 70);
    await page.mouse.move(1000, 600, { steps: 25 }); await page.waitForTimeout(5000); mark('scrubbed');
    console.log('heatmap at', (await page.innerText('body')).match(/(Today|Yesterday) \d\d:\d\d/)?.[0]);
    await page.screenshot({ path: path.join(OUT, 'heatmap-incident.png') });
    await page.mouse.move(TILE[0], TILE[1], { steps: 25 }); await page.waitForTimeout(2500); mark('tile');

    // 2. The device: live first, then its last 24 h, back to the freeze and past it
    await page.mouse.click(TILE[0], TILE[1]);
    const archive = page.getByRole('button', { name: 'Restart mode' });
    await archive.waitFor({ timeout: 30000 }); await page.waitForTimeout(7000); mark('live');
    const title = (await page.locator('.MuiDialog-root, .MuiModal-root').last().innerText().catch(() => '')).split('\n')[0];
    if (!title.includes(DEVICE)) console.log('WARNING modal title is', JSON.stringify(title));
    await glide(page, ...(await center(archive)), 700); await page.waitForTimeout(7000); mark('archive');
    // the archive slider: its right end is now, one pixel is about 47 s of the day
    const ax = async (t) => { const r = await page.locator('.MuiSlider-rail').last().boundingBox(); return r.x + r.width * (1 - ago(t) / 86400); };
    const athumb = page.locator('.MuiSlider-thumb').last();
    // the chunk holds the stuck banner from about 90 s before the detection; a drag lands about 60 s late (one pixel is ~47 s), so aim early
    mark('seek-freeze'); await drag(page, athumb, await ax(t0s - 100), 45, 70);
    await page.mouse.move(960, 560, { steps: 20 }); await page.waitForTimeout(12000); mark('freeze-shown');
    await page.screenshot({ path: path.join(OUT, 'archive-freeze.png') });
    mark('seek-after'); await drag(page, athumb, await ax(t0s + 7 * 60), 25, 70);
    await page.mouse.move(960, 560, { steps: 20 }); await page.waitForTimeout(12000); mark('after-shown');
    await page.screenshot({ path: path.join(OUT, 'archive-after.png') });
    await glide(page, ...(await center(page.locator('button:has([data-testid="CloseIcon"])').last())), 600);
    await page.waitForTimeout(1500); mark('closed');

    // 3. The incident, from the Monitoring menu
    await glide(page, ...(await center(page.getByText('Monitoring', { exact: true }).first())), 500); await page.waitForTimeout(1200);
    await glide(page, ...(await center(page.getByRole('menuitem', { name: /Incidents/ }).first())), 500);
    await page.getByText('Incident Summary').first().waitFor({ timeout: 60000 }); await page.mouse.move(1700, 500); await page.waitForTimeout(5000); mark('incidents');
    const row = page.locator('tr', { hasText: INCIDENT }).first(); await row.waitFor({ timeout: 30000 });
    for (let i = 0; i < 40; i++) { const b = await row.boundingBox(); if (b && b.y > 200 && b.y < 420) break; await page.mouse.wheel(0, b && b.y < 200 ? -120 : 120); await page.waitForTimeout(160); }
    await page.waitForTimeout(1200); mark('row');
    await glide(page, ...(await center(row.locator('button').first())), 900);
    await page.waitForFunction(() => [...document.images].filter(i => /alerts\/freeze/.test(i.src)).every(i => i.complete && i.naturalWidth > 0), null, { timeout: 30000 }).catch(() => console.log('some frames did not load'));
    await page.waitForTimeout(2500); mark('expanded');
    await page.screenshot({ path: path.join(OUT, 'incident.png') });
    for (const label of ['Start', 'Frame -2', 'Frame -1', 'Current']) {
      const l = page.getByText(label, { exact: true }).first(); const b = await l.boundingBox().catch(() => null);
      if (b) { await page.mouse.move(b.x + b.width / 2, b.y + 55, { steps: 18 }); await page.waitForTimeout(1300); }
    }
    const thr = page.getByText(/^Threshold:/).first(); const tb = await thr.boundingBox().catch(() => null);
    if (tb) { await page.mouse.move(tb.x + 60, tb.y + 20, { steps: 18 }); await page.waitForTimeout(3500); }
    mark('end');
  } catch (e) { console.log('ERROR', e.message.slice(0, 200)); await page.screenshot({ path: path.join(OUT, 'mon-error.png') }).catch(() => {}); }
  const vid = page.video(); await ctx.close(); fs.copyFileSync(await vid.path(), path.join(OUT, 'mon.webm'));
  fs.writeFileSync(path.join(OUT, 'mon.marks.json'), JSON.stringify({ marks, incident: INCIDENT, heatmap_minute: hms(t0s + 60) }, null, 1)); await browser.close();
  console.log('clip mon', marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
