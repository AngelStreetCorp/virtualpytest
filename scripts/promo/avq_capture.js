// Assets for video 13 (A/V quality): rpitest, stb4 on vpt-pi3, nothing driven. The Device page filtered to
// stb4, its preview's Audio/Video Quality icon, the AVQ page (live chips and metrics), then a click in the
// "Last 24h" timeline on a freeze: the player seeks there and the chips turn red. Optionally the FRAMES tab.
// The operator's logo must never be on screen (TASK-28 §13): pick an AVQ_AT whose frame has none, run
// `scout` first and look at every still.
// Usage: AVQ_AT=07:46:33 AVQ_BACK=07:54:52 node avq_capture.js scout   -> raw13/scout-*.png
//        AVQ_AT=07:46:33 AVQ_BACK=07:54:52 node avq_capture.js         -> raw13/avq.mp4 + avq.marks.json
// AVQ_AT: the incident (player black, chips red); AVQ_BACK: the picture back; FRAME_STEPS (default 6) → presses in FRAMES.
// AVQ_AT is a local wall-clock time within the last 24 h (the machine's time zone), at least ~15 min old:
// the archive is written in 10-minute chunks, a newer seek plays black.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const DIR = __dirname; const OUT = path.join(DIR, 'raw13'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, BASE, url, CURSOR, redact, relay, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });   // player + timeline on one screen
const CARD = 'stb4 - vpt-pi3';

// HH:MM[:SS] local wall-clock time within the last 24 h -> epoch ms
function atMs(at, name) {
  const [h, m, sec] = (at || '').split(':').map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) throw new Error(`set ${name}=HH:MM[:SS]`);
  const d = new Date(); d.setHours(h, m, sec || 0, 0); if (d > new Date()) d.setDate(d.getDate() - 1);
  return d.getTime();
}
// the 10-minute archive chunk the player must load for that time, e.g. "/7/chunk_10min_4.mp4"
const chunkOf = ms => { const d = new Date(ms); return `/${d.getHours()}/chunk_10min_${Math.floor(d.getMinutes() / 10)}.mp4`; };

async function newContext(browser) {
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR);
  await ctx.addInitScript(([origin, labels]) => {
    if (location.origin !== origin) return;
    localStorage.setItem('rec_filters_target', JSON.stringify(labels));
    localStorage.setItem('rec_filters_model', '[]'); localStorage.setItem('rec_filters_flag', '[]');
  }, [new URL(BASE).origin, [CARD]]);
  await relay(ctx); return ctx;
}

// The whole walk; `shot(name)` takes a still at each beat (scout looks at them, the take keeps them).
async function walk(page, mark, shot) {
  await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2000);
  await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 }); await page.mouse.move(700, 500);
  // the page prunes saved filters that match no device while its list is still empty (filter wiped on load), so
  // pick stb4 in the Target dropdown once the list is there, as a user would
  await page.locator(`text=/^${CARD}$/`).first().waitFor({ timeout: 90000 }); await page.waitForTimeout(3000);
  if (!/Device \(1\)/.test(await page.locator('body').innerText())) {
    await glide(page, ...(await page.locator('.MuiSelect-select').first().boundingBox().then(b => [b.x + b.width / 2, b.y + b.height / 2])), 800);
    const opt = page.locator('[role="option"]').filter({ hasText: new RegExp(`^${CARD}$`) }).first();
    await glide(page, ...(await opt.boundingBox().then(b => [b.x + b.width / 2, b.y + b.height / 2])), 600);
    await page.keyboard.press('Escape'); await page.mouse.move(700, 500, { steps: 15 });
  }
  await page.waitForFunction(() => /Device \(1\)/.test(document.body.innerText), null, { timeout: 30000 });
  await page.locator(`text=/^${CARD}$/`).first().waitFor({ timeout: 90000 }); await page.waitForTimeout(12000);
  mark('grid'); await shot('grid');
  const link = page.getByRole('button', { name: 'Audio/Video Quality' }).first(); await link.waitFor({ timeout: 20000 });
  const lb = await link.boundingBox(); await page.mouse.move(lb.x + lb.width / 2, lb.y + lb.height / 2, { steps: 30 });
  await page.waitForTimeout(1800); mark('tooltip'); await shot('tooltip');
  await page.mouse.click(lb.x + lb.width / 2, lb.y + lb.height / 2); mark('click');
  await page.getByText(/Last 24h \(/).first().waitFor({ timeout: 60000 }); await page.mouse.move(900, 300, { steps: 20 });
  await page.waitForTimeout(9000); mark('avq'); await shot('avq-live');
  // the live picture plays for a while: that is the 24/7 measure, chips and metrics moving
  await page.mouse.move(600, 330, { steps: 25 }); await page.waitForTimeout(8000); mark('live'); await shot('live');
  // the timeline: hover from the right end back to the incident (AVQ_AT), click: the player seeks there
  // no scroll: at 1600x900 the player and the timeline's top rows share the screen
  const svg = page.locator('svg[style*="pointer"]').first(); const r = await svg.boundingBox();
  const xOf = ms => { const t1 = Date.now(), t0 = t1 - 24 * 3600_000; const x = r.x + ((ms - t0) / (t1 - t0)) * r.width;
    if (x < r.x || x > r.x + r.width) throw new Error('time outside the last 24 h'); return x; };
  const y = Math.min(r.y + r.height * 0.3, 860);
  const seek = async (ms, label) => {
    await page.mouse.click(xOf(ms), y); mark(label);
    await page.mouse.move(r.x + r.width * 0.3, r.y - 120, { steps: 12 });   // off the timeline: its rows show hover tooltips (transcript text)
    // the archive chunk comes in 4 MB ranges through the relay (5-20 s): wait for that chunk's decoded frame, the build cuts the wait
    await page.waitForFunction(c => [...document.querySelectorAll('video')].some(v => v.offsetWidth && v.readyState >= 3 && v.videoWidth && v.currentSrc.includes(c)), chunkOf(ms), { timeout: 60000 });
    mark(`${label}-loaded`);
  };
  const black = atMs(process.env.AVQ_AT, 'AVQ_AT'), back = atMs(process.env.AVQ_BACK, 'AVQ_BACK');
  await page.mouse.move(r.x + r.width - 8, y, { steps: 25 }); await page.waitForTimeout(800);
  await page.mouse.move(xOf(black), y, { steps: 45 }); await page.waitForTimeout(1500); mark('hover'); await shot('hover');
  await seek(black, 'seek'); await page.waitForTimeout(2500);
  await page.mouse.move(r.x + r.width * 0.3, r.y - 120, { steps: 20 }); await page.waitForTimeout(3000);
  mark('incident'); await shot('incident');
  // the picture comes back (AVQ_BACK): a later click on the timeline
  await page.mouse.move(xOf(back), y, { steps: 25 }); await page.waitForTimeout(800);
  await seek(back, 'back'); await page.waitForTimeout(4000); mark('recovered'); await shot('recovered');
  // FRAMES: the stills the scores were computed from, stepped one by one (→)
  const frames = page.getByRole('tab', { name: /^frames$/i }).first();
  await glide(page, ...(await frames.boundingBox().then(b => [b.x + b.width / 2, b.y + b.height / 2])), 700);
  await page.waitForTimeout(6000); mark('frames'); await shot('frames');
  const next = page.getByRole('button', { name: /next frame/i }).first();
  const nb = await next.boundingBox().catch(() => null);
  for (let i = 0; i < Number(process.env.FRAME_STEPS || 6); i++) {
    if (nb) await glide(page, nb.x + nb.width / 2, nb.y + nb.height / 2, 300); else await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(1600);
  }
  mark('stepped'); await shot('stepped');
  await page.waitForTimeout(1500); mark('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true }); const ctx = await newContext(browser); const page = await ctx.newPage();
  const stop = scout ? null : await startRecorder(page, 'avq');
  const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-${name}.png`) });
  try { await walk(page, mark, shot); }
  catch (e) { console.log('ERROR', redact(e.message).slice(0, 200)); await shot('error').catch(() => {}); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'avq.marks.json'), JSON.stringify({ marks, at: process.env.AVQ_AT, back: process.env.AVQ_BACK }, null, 1));
  console.log(scout ? 'scout' : 'clip avq', marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
