// Video 24 (Nintendo Switch part): Device page on RPI1-server -> switch1 (vpt-pi3/device2) opened big -> Take Control ->
// the Pro Controller picture is CLICKED: HOME, left/right across the game tiles, launch Dragon Ball Xenoverse 2 (opening
// animation), HOME, launch Super Kirby Clash, walk Kirby around the village with left/right, Release.
// Every key is a real click on the controller picture; the only API calls are reads (lock list). Needs a vpt-lease on
// vpt-pi3/device2, the Switch awake (Auto-Sleep Never), vpt-procon connected.
// Usage: PROMO_BASE=https://virtualpytest.angelstreet.io node switch_capture.js [scout]
//   scout: same walk, no recording, scout-sw-*.png. Take: raw24/switch.mp4 + switch.marks.json + take-sw-*.png.
if (!process.env.PROMO_SERVER) throw new Error('PROMO_SERVER is required (public URL of the server, e.g. https://<server>.angelstreet.io)');
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw24'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, api, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const HOST = 'vpt-pi3', DEVICE = 'device2', NAME = 'switch1', OTHER = 'FireTv', SERVER = 'RPI1-server';
// controller picture buttons, device modal with the remote panel open: measured on the 1920 screenshot, divided by 1.2 (CSS px)
const px = (x, y) => [x / 1.2, y / 1.2];
const KEY = { UP: px(1637, 615), DOWN: px(1637, 649), LEFT: px(1621, 632), RIGHT: px(1654, 632), A: px(1807, 583), B: px(1780, 608),
  X: px(1780, 560), Y: px(1753, 583), HOME: px(1713, 584), PLUS: px(1732, 557), MINUS: px(1647, 557), CAPTURE: px(1665, 584) };
const GAME = { xeno: +(process.env.XENO || 3), kirby: +(process.env.KIRBY || 3) };   // tile index on the Home menu (1 = last played)

const center = async l => { const b = await l.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; };
const targetSelect = page => page.locator('.MuiSelect-select').filter({ hasText: /Targets?|FireTv|switch1/ }).first();
async function openTargets(page) {
  const box = page.locator('input[placeholder="Search targets..."]').first();
  for (let a = 1; a <= 4; a++) {
    await glide(page, ...(await center(targetSelect(page))), 500);
    if (await box.waitFor({ timeout: 4000 }).then(() => true).catch(() => false)) return;
    await page.keyboard.press('Escape'); await page.waitForTimeout(800);
  }
  throw new Error('Target dropdown did not open');
}
async function tick(page, name) {
  const box = page.locator('input[placeholder="Search targets..."]').first();
  await box.fill(''); await box.pressSequentially(name, { delay: 40 }); await page.waitForTimeout(700);
  await page.locator('[role="option"]').filter({ hasText: new RegExp(`^${name} - ${HOST}$`) }).first().click(); await page.waitForTimeout(500);
}

async function walk(page, mark, shot, log, startRec) {
  await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(4000);
  const sel = page.locator('.MuiFormControl-root:has(label:has-text("Server")) .MuiSelect-select').first();
  await sel.waitFor({ timeout: 30000 });
  if ((await sel.innerText()).trim() !== SERVER) {
    await sel.click(); await page.waitForTimeout(800);
    await page.locator('[role="option"]').filter({ hasText: new RegExp(`^${SERVER}`) }).first().click(); await page.waitForTimeout(9000);
  }
  const tl = page.locator(`text=/^${NAME} - ${HOST}$/`).first();   // 36 tiles, 24 per page: the tile may be on page 2
  if (!(await tl.waitFor({ timeout: 20000 }).then(() => true).catch(() => false))) {
    await page.getByRole('button', { name: 'Go to next page' }).click(); await page.waitForTimeout(3000); }
  await tl.waitFor({ timeout: 60000 });
  await page.mouse.move(800, 300); await page.waitForTimeout(20000);   // tiles load
  // off camera: show only the two vpt-pi3 devices of this video in the Target filter
  await openTargets(page);
  const clear = page.locator('.MuiPopover-root, .MuiMenu-root').last().getByText(/^Clear$/).first();
  if (await clear.isEnabled({ timeout: 1500 }).catch(() => false)) await clear.click();
  await tick(page, NAME); await tick(page, OTHER);
  await page.mouse.click(1300, 650); await page.waitForTimeout(900);
  await page.mouse.move(800, 300); await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(12000);
  await startRec(); mark('page'); await shot('page'); await page.waitForTimeout(3500);

  const tile = page.locator(`text=/^${NAME} - ${HOST}$/`).first(); const tb = await tile.boundingBox();
  await glide(page, tb.x + 90, tb.y + tb.height + 90, 700); await page.waitForTimeout(6000);
  const take = page.getByRole('button', { name: /take control/i }).first();
  await take.waitFor({ timeout: 20000 });
  await glide(page, ...(await center(take)), 700);
  await page.getByRole('button', { name: /^release$/i }).first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(4000); mark('control'); await shot('control');
  const press = async (k, pause = 1500) => { await glide(page, ...KEY[k], 400); await page.waitForTimeout(pause); };
  const hover = async k => { await page.mouse.move(...KEY[k], { steps: 20 }); };

  // HOME menu, then step across the game tiles
  await press('HOME', 4000); mark('home'); await shot('home');
  for (let i = 0; i < 3; i++) { await press('RIGHT', 1400); await shot(`tile-r${i + 1}`); }
  for (let i = 0; i < 3; i++) await press('LEFT', 1400);
  await shot('tile-back');
  // Dragon Ball Xenoverse 2
  for (let i = 1; i < GAME.xeno; i++) await press('RIGHT', 1200);
  await shot('xeno-tile'); await press('A', 600); mark('xeno-launch');
  await page.waitForTimeout(3000); await shot('xeno-prompt');
  if (process.env.XENO_PROMPT === '1') await press('A', 800);
  // the stream lags 10-15 s behind the buttons: wait 45 s so the real intro animation plays on screen (xeno-anim is set after checking the frames)
  for (let i = 0; i < 12; i++) { await page.waitForTimeout(5000); await shot(`xeno-${i}`); if (i === 3) mark('xeno-anim'); }
  mark('xeno-end');
  // Super Kirby Clash
  await press('HOME', 4000); await shot('home2');
  for (let i = 1; i < GAME.kirby; i++) await press('RIGHT', 1200);
  await shot('kirby-tile'); await press('A', 600); mark('kirby-launch');
  await page.waitForTimeout(3000); await shot('kirby-prompt');
  if (process.env.KIRBY_PROMPT !== '0') await press('A', 800);
  await page.waitForTimeout(14000); await press('A', 9000); await shot('kirby-title'); await press('A', 9000); await shot('kirby-loading');
  mark('kirby-a');
  for (let i = 0; i < 8; i++) { await press('A', 2200); await shot(`kirby-${i}`); }
  mark('kirby-end');
  const rel = page.getByRole('button', { name: /^release$/i }).first();
  await glide(page, ...(await center(rel)), 700); await page.waitForTimeout(3500);
  mark('end'); await shot('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const locks = (await api('GET', '/server/control/lockedDevices')).locked_devices || {};
  if (locks[`${HOST}:${DEVICE}`]) { console.log(`${HOST}:${DEVICE} is locked, stop`); return; }
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true, colorScheme: 'dark' });
  await ctx.addInitScript(CURSOR); await ctx.addInitScript(() => { try { localStorage.setItem('theme-mode', 'dark'); } catch (e) {} }); const page = await ctx.newPage();
  ctx.on('page', p => { if (p !== page) p.close().catch(() => {}); });
  let stop = null; const marks = []; let t0 = Date.now();
  const startRec = async () => { if (!scout) stop = await startRecorder(page, 'switch'); t0 = Date.now(); };
  const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); };
  const log = s => console.log(redact(s));
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-sw-${name}.png`) });
  try { await walk(page, mark, shot, log, startRec); }
  catch (e) {
    log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); process.exitCode = 1;
    const rel = page.getByRole('button', { name: /^release$/i }).first();   // do not leave our own control lock behind
    if (await rel.isVisible().catch(() => false)) await rel.click().catch(() => {});
    await page.waitForTimeout(2500);
  }
  if (!scout) fs.writeFileSync(path.join(OUT, 'switch.marks.json'), JSON.stringify({ marks }, null, 1));
  if (stop) await stop();
  await ctx.close(); await browser.close();
  console.log(marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
