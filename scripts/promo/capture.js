// Capture stills + recorded clips for the promo video.
// Usage: node capture.js [stills|clips|all]
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs');
const path = require('path');

const DIR = __dirname;
const OUT = path.join(DIR, 'raw');
fs.mkdirSync(OUT, { recursive: true });
const TOKEN = fs.readFileSync(path.join(DIR, '.token'), 'utf8').trim();
const BASE = process.env.PROMO_BASE || 'http://localhost:5073';
const reports = JSON.parse(fs.readFileSync(path.join(DIR, 'reports.json'), 'utf8'));
const mode = process.argv[2] || 'all';

const VIEW = { width: 1920, height: 1080 };

// Fake cursor so recorded clips show where the "user" clicks (headless has none).
const CURSOR_SCRIPT = `
(() => {
  const mk = () => {
    if (document.getElementById('__promo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__promo_cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px);';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2 L4 19 L8.5 15 L11.5 22 L14.5 20.8 L11.5 14 L17.5 14 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    window.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    window.addEventListener('mousedown', () => { c.style.transform = 'translate(-3px,-2px) scale(0.85)'; }, true);
    window.addEventListener('mouseup', () => { c.style.transform = 'translate(-3px,-2px) scale(1)'; }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mk); else mk();
})();`;

const url = (p) => `${BASE}${p}${p.includes('?') ? '&' : '?'}auto_signed=${TOKEN}`;

async function glideClick(page, locator, { pause = 500, steps = 28 } = {}) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error('no bounding box');
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await page.mouse.move(x, y, { steps });
  await page.waitForTimeout(pause);
  await page.mouse.click(x, y);
}

async function stills() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW, deviceScaleFactor: 1, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();
  await page.goto(url('/'), { waitUntil: 'load', timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(3000);
  const shots = [
    ['dashboard', '/', 5000, false],
    ['devices', '/device-control', 7000, false],
    ['run-tests', '/test-execution/run-tests', 6000, false],
    ['analytics-kpi', '/monitoring/analytics?section=kpi', 15000, false],
    ['analytics-overview', '/monitoring/analytics?section=overview', 15000, false],
    ['analytics-devices', '/monitoring/analytics?section=devices', 15000, false],
    ['heatmap', '/monitoring/heatmap', 8000, false],
    ['incidents', '/monitoring/incidents', 6000, false],
  ];
  for (const [name, p, wait, full] of shots) {
    await page.goto(url(p), { waitUntil: 'load', timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(wait);
    await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: full });
    console.log('still', name);
  }
  for (const [name, u] of Object.entries(reports)) {
    await page.goto(u, { waitUntil: 'load', timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(4000);
    await page.screenshot({ path: path.join(OUT, `report-${name}.png`), fullPage: true });
    console.log('still report', name);
  }
  await browser.close();
}

async function recordClip(name, fn) {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: VIEW, deviceScaleFactor: 1, ignoreHTTPSErrors: true,
    recordVideo: { dir: path.join(OUT, 'video-' + name), size: VIEW },
  });
  await ctx.addInitScript(CURSOR_SCRIPT);
  const page = await ctx.newPage();
  const marks = [];
  const mark = (label) => { marks.push({ label, t: Date.now() }); };
  const t0 = Date.now();
  try {
    await fn(page, mark);
  } catch (e) {
    console.log('clip', name, 'ERROR', e.message);
  }
  const vid = page.video();
  await ctx.close();
  const p = await vid.path();
  const dest = path.join(OUT, `${name}.webm`);
  fs.copyFileSync(p, dest);
  fs.writeFileSync(path.join(OUT, `${name}.marks.json`), JSON.stringify(marks.map(m => ({ label: m.label, t: (m.t - t0) / 1000 })), null, 1));
  await browser.close();
  console.log('clip', name, '->', dest, marks.map(m => `${m.label}@${((m.t - t0) / 1000).toFixed(1)}s`).join(' '));
}

const only = process.argv[3];
async function clips() {
  // Clip A: device page -> open stream modal on host-clone-1 -> Take Control -> Show Remote
  if (!only || only === 'devices') await recordClip('devices', async (page, mark) => {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(2500);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 60000 }).catch(() => {});
    await page.mouse.move(960, 700);
    await page.waitForTimeout(7000);
    mark('loaded');
    const title = page.locator('text=/^host-clone-1$/').first();
    await title.waitFor({ timeout: 20000 });
    const tb = await title.boundingBox();
    // Thumbnail sits under the title row: click its centre (card ~270px wide, ~150px tall).
    const tx = tb.x + 120, ty = tb.y + tb.height + 80;
    await page.mouse.move(tx, ty, { steps: 30 });
    await page.waitForTimeout(700);
    await page.mouse.click(tx, ty);
    mark('modal');
    await page.waitForTimeout(4000);
    const take = page.getByRole('button', { name: /take control/i }).first();
    if (await take.count()) { await glideClick(page, take, { pause: 500 }); mark('take-control'); await page.waitForTimeout(3500); }
    const remote = page.getByRole('button', { name: /show remote/i }).first();
    if (await remote.count()) { await glideClick(page, remote, { pause: 500 }); mark('show-remote'); await page.waitForTimeout(3500); }
    await page.mouse.move(1500, 900, { steps: 30 });
    await page.waitForTimeout(2500);
    mark('end');
    const release = page.getByRole('button', { name: /release control/i }).first();
    if (await release.count()) { await release.click().catch(() => {}); await page.waitForTimeout(800); }
  });

  // Clip B: run tests -> tick host-clone-1 -> pick "Device Get Info" -> Run -> execution appears
  if (!only || only === 'run-tests') await recordClip('run-tests', async (page, mark) => {
    await page.goto(url('/'), { waitUntil: 'load', timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(2500);
    await page.goto(url('/test-execution/run-tests'), { waitUntil: 'load', timeout: 60000 }).catch(() => {});
    await page.mouse.move(300, 500);
    await page.waitForTimeout(7000);
    mark('loaded');
    // 1) pick the script first (picking a target first filters the list and re-renders it)
    const script = page.locator('text=/^Smoke Device Control$/').first();
    await script.waitFor({ timeout: 20000 });
    await glideClick(page, script, { pause: 500 });
    mark('script');
    await page.waitForTimeout(1500);
    // 2) tick the host-clone-1 target checkbox
    const row = page.locator('text=/^host-clone-1$/').first();
    await row.waitFor({ timeout: 20000 });
    const rb = await row.boundingBox();
    if (rb.y > 700) throw new Error('targets list did not load');
    const cx = rb.x - 18, cy = rb.y + rb.height / 2;
    await page.mouse.move(cx, cy, { steps: 28 });
    await page.waitForTimeout(500);
    await page.mouse.click(cx, cy);
    mark('target');
    await page.waitForTimeout(1500);
    // 3) Run (verify it is enabled; if not, re-tick the target once)
    const run = page.getByRole('button', { name: /^run$/i }).first();
    if (!(await run.isEnabled())) {
      console.log('run disabled, re-ticking target');
      await page.mouse.click(cx, cy); await page.waitForTimeout(1200);
    }
    console.log('run enabled:', await run.isEnabled());
    await glideClick(page, run, { pause: 700 });
    mark('run');
    await page.waitForTimeout(9000);
    await page.mouse.move(960, 900, { steps: 30 });
    await page.waitForTimeout(3000);
    mark('end');
  });
}

(async () => {
  if (mode === 'stills' || mode === 'all') await stills();
  if (mode === 'clips' || mode === 'all') await clips();
})();
