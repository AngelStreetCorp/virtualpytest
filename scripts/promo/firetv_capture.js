// Video 24 (Fire TV part): Device page on RPI1-server -> FireTv tile opened big -> Take Control -> the on-screen
// remote picture is CLICKED: HOME, D-pad to the YouTube tile, OK, YouTube Music, a video, BACK, HOME, Release.
// Every key is a real click on the remote picture. The only API call is a read (takeScreenshot) whose text (tesseract)
// tells the script where the focus is, so the D-pad presses stop at the right tile; nothing is sent through the API.
// SEED (off camera, once): as guest, search "Big Buck Bunny" in YouTube and watch it a few seconds, so it shows on the home feed.
// Needs a vpt-lease on vpt-pi3/device1 and YouTube installed + past its first-run screens (guest) on the stick.
// Usage: PROMO_BASE=https://virtualpytest.angelstreet.io node firetv_capture.js [scout]
//   scout: same walk, no recording, scout-*.png. Take: raw24/firetv.mp4 + firetv.marks.json + take-ft-*.png.
if (!process.env.PROMO_SERVER) throw new Error('PROMO_SERVER is required (public URL of the server, e.g. https://<server>.angelstreet.io)');
// PROMO_SERVER: API reads go to that server (the page itself is the main site)
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path'); const cp = require('child_process');
const OUT = path.join(__dirname, 'raw24'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, api, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const HOST = 'vpt-pi3', DEVICE = 'device1', NAME = 'FireTv', OTHER = 'switch1', SERVER = 'RPI1-server';
const VIDEO = process.env.VIDEO || 'Official Blender|Blender Foundation';   // Blender open movies (CC BY)
// remote picture buttons, CSS px in the 1600x900 page, device modal with the remote panel open (measured on the 1920 screenshot / 1.2)
const KEY = { UP: [1407, 277], DOWN: [1407, 401], LEFT: [1339, 340], RIGHT: [1472, 340], OK: [1405, 339], BACK: [1352, 451], HOME: [1408, 451] };

// ---- reading the Fire TV screen (read-only) -------------------------------------------------------------------
let n = 0;
async function ocr(box, psm = 6) {   // box = [x, y, w, h] in the 1920x1080 device frame; returns the text in it
  const r = await api('POST', '/server/remote/takeScreenshot', { host_name: HOST, device_id: DEVICE, remote_type: 'vega' });
  if (!r.screenshot) throw new Error('no device screenshot');
  const f = path.join(OUT, `.ocr-${process.pid}.png`); fs.writeFileSync(f, Buffer.from(r.screenshot, 'base64'));
  const py = `from PIL import Image,ImageOps;im=Image.open("${f}").convert("L").crop((${box[0]},${box[1]},${box[0] + box[2]},${box[1] + box[3]}));im=ImageOps.autocontrast(im).resize((im.width*2,im.height*2));im.save("${f}.c.png")`;
  cp.execFileSync('python3', ['-c', py]);
  const t = cp.execFileSync('tesseract', [`${f}.c.png`, 'stdout', '--psm', String(psm)], { stdio: ['ignore', 'pipe', 'ignore'] }).toString();
  n++; return t.replace(/\s+/g, ' ').trim();
}
const TOP = [80, 90, 1100, 190];        // title / hint of the focused tile on the Fire TV home
const ROWHEAD = [140, 150, 600, 90];     // YouTube home: heading of the focused row ("Recommended", "Pop Music")
const CAPTION_RES = [140, 590, 640, 130];  // YouTube search results: title of the focused first result
const QUERY = process.env.QUERY || 'big buck bunny blender';
const CAPTION = [140, 660, 900, 200];    // YouTube home: title of the focused video

// ---- helpers ---------------------------------------------------------------------------------------------------
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
async function tick(page, name) {   // search a target and tick it
  const box = page.locator('input[placeholder="Search targets..."]').first();
  await box.fill(''); await box.pressSequentially(name, { delay: 40 }); await page.waitForTimeout(700);
  await page.locator('[role="option"]').filter({ hasText: new RegExp(`^${name} - ${HOST}$`) }).first().click(); await page.waitForTimeout(500);
}

async function prep(log) {   // off camera: YouTube resumes its last video when it is only in the background, so stop it first
  for (let i = 0; i < 3; i++) { await api('POST', '/server/remote/executeCommand', { host_name: HOST, device_id: DEVICE, command: 'close_app', params: { package: 'com.amazon.firetv.youtube.main' }, remote_type: 'vega' }); await new Promise(r => setTimeout(r, 3500)); }
  await api('POST', '/server/remote/executeCommand', { host_name: HOST, device_id: DEVICE, command: 'press_key', params: { key: 'HOME' }, remote_type: 'vega' });
  log('prep: YouTube stopped, Fire TV on Home');
}

async function walk(page, mark, shot, log, startRec, scout) {
  await prep(log);
  await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(4000);
  const sel = page.locator('.MuiFormControl-root:has(label:has-text("Server")) .MuiSelect-select').first();
  await sel.waitFor({ timeout: 30000 });
  if ((await sel.innerText()).trim() !== SERVER) {
    await sel.click(); await page.waitForTimeout(800);
    await page.locator('[role="option"]').filter({ hasText: new RegExp(`^${SERVER}`) }).first().click(); await page.waitForTimeout(9000);
  }
  await page.locator(`text=/^${NAME} - ${HOST}$/`).first().waitFor({ timeout: 60000 });
  await page.mouse.move(800, 300); await page.waitForTimeout(20000);   // tiles load
  // off camera: show only the two vpt-pi3 devices of this video in the Target filter
  await openTargets(page);
  const clear = page.locator('.MuiPopover-root, .MuiMenu-root').last().getByText(/^Clear$/).first();
  if (await clear.isEnabled({ timeout: 1500 }).catch(() => false)) await clear.click();
  await tick(page, NAME); await tick(page, OTHER);
  await page.mouse.click(1300, 650); await page.waitForTimeout(900);   // backdrop closes the menu (not the AI bubble bottom-left)
  await page.mouse.move(800, 300); await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(12000);
  // off camera: HOME, then D-pad (API presses) until the YouTube tile has focus, so the take only shows the launcher and OK
  const apiKey = async k => { await api('POST', '/server/remote/executeCommand', { host_name: HOST, device_id: DEVICE, command: 'press_key', params: { key: k }, remote_type: 'vega' }); };
  await apiKey('HOME'); await page.waitForTimeout(14000);
  let onRow = false;
  for (let i = 0; i < 5 && !onRow; i++) { await apiKey('DOWN'); await page.waitForTimeout(3500); onRow = /manage this app|remove or manage/i.test(await ocr(TOP)); }
  if (!onRow) throw new Error('never reached the apps row');
  let onYt = /youtube/i.test(await ocr(TOP));
  for (let i = 0; i < 5 && !onYt; i++) { await apiKey('RIGHT'); await page.waitForTimeout(2500); onYt = /youtube/i.test(await ocr(TOP)); }
  if (!onYt) throw new Error('YouTube tile not reached');
  await startRec(); mark('page'); await shot('page'); await page.waitForTimeout(3500);

  // open the Fire TV big: click inside its preview
  const tile = page.locator(`text=/^${NAME} - ${HOST}$/`).first(); const tb = await tile.boundingBox();
  await glide(page, tb.x + 90, tb.y + tb.height + 90, 700); await page.waitForTimeout(6000);
  const take = page.getByRole('button', { name: /take control/i }).first();
  await take.waitFor({ timeout: 20000 });
  await glide(page, ...(await center(take)), 700);
  await page.getByRole('button', { name: /^release$/i }).first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(4000); mark('control'); await shot('control');
  const press = async (k, pause = 1800) => { await glide(page, ...KEY[k], 500); await page.waitForTimeout(pause); };

  // the launcher is already on screen with the YouTube tile focused (positioned off camera): HOME beat = this launcher
  await page.waitForTimeout(1500); mark('home'); await shot('home');
  await page.waitForTimeout(1200); await press('OK', 1000); mark('youtube');
  await page.waitForTimeout(16000); await shot('youtube');
  log('youtube opened: ' + (await ocr([0, 0, 1920, 1080], 11)).slice(0, 100));

  // YouTube Home (fresh start, guest): the feed is different on every launch, so the video is found with YouTube's own search.
  // UP (twice at most) puts the focus on the Search bar, OK opens the keyboard, the query is typed through the API
  // (the remote picture has no keyboard; the only non-click input of the walk), LEFT + OK takes the first suggestion,
  // and the first result must be the official Blender upload (checked by its caption).
  let onSearch = false;
  for (let i = 0; i < 3 && !onSearch; i++) { await press('UP', 2500); onSearch = /search/i.test(await ocr([150, 60, 740, 90], 7)); }
  mark('search'); await press('OK', 3500);
  await api('POST', '/server/remote/executeCommand', { host_name: HOST, device_id: DEVICE, command: 'input_text', params: { text: QUERY }, remote_type: 'vega' });
  await page.waitForTimeout(3500); await shot('search-typed');
  await press('LEFT', 1500); await press('OK', 8000); await shot('results');
  const cap = await ocr(CAPTION_RES, 6); log('first result: ' + cap);
  if (!new RegExp(VIDEO, 'i').test(cap)) throw new Error(`first result is not "${VIDEO}": ${cap}`);
  await page.waitForTimeout(1200); await shot('video-pick');
  await press('OK', 3000); mark('video-start');
  // a pre-roll ad: mark it, wait for the Skip button without a countdown, press OK on it
  const AD = [1250, 760, 670, 280];
  let t = await ocr(AD, 6); let ad = /skip|sponsored|ad\b/i.test(t);
  if (ad) {
    mark('ad-start'); log('ad: ' + t.slice(0, 60)); await shot('ad');
    for (let i = 0; i < 40; i++) { t = await ocr(AD, 6); if (/skip/i.test(t) && !/skip\D{0,6}\d/i.test(t)) break; await page.waitForTimeout(2500); }
    await press('OK', 2500); mark('ad-end');
  }
  await page.waitForTimeout(3000); await shot('video-start');
  await page.waitForTimeout(10000); mark('playing'); await shot('playing');

  // back out
  await press('BACK', 3500); await press('HOME', 12000); mark('back-home'); await shot('back-home');
  // Release
  const rel = page.getByRole('button', { name: /^release$/i }).first();
  await glide(page, ...(await center(rel)), 700); await page.waitForTimeout(3500);
  mark('end'); await shot('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const locks = (await api('GET', '/server/control/lockedDevices')).locked_devices || {};
  if (locks[`${HOST}:${DEVICE}`]) { console.log(`${HOST}:${DEVICE} is locked, stop`); return; }
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await ctx.addInitScript(() => { try { localStorage.setItem('theme-mode', 'dark'); } catch (e) {} }); const page = await ctx.newPage();   // theme-mode=dark: the VirtualPyTest app in dark mode
  ctx.on('page', p => { if (p !== page) p.close().catch(() => {}); });
  let stop = null; const marks = []; let t0 = Date.now();
  const startRec = async () => { if (!scout) stop = await startRecorder(page, 'firetv'); t0 = Date.now(); };
  const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); };
  const log = s => console.log(redact(s));
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-ft-${name}.png`) });
  try { await walk(page, mark, shot, log, startRec, scout); }
  catch (e) {
    log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); process.exitCode = 1;
    const rel = page.getByRole('button', { name: /^release$/i }).first();   // do not leave our own control lock behind
    if (await rel.isVisible().catch(() => false)) await rel.click().catch(() => {});
    await page.waitForTimeout(2500);
  }
  // on an error leave the TV on Home and the control released
  try { await api('POST', '/server/remote/executeCommand', { host_name: HOST, device_id: DEVICE, command: 'press_key', params: { key: 'HOME' }, remote_type: 'vega' }); } catch (e) {}
  if (!scout) fs.writeFileSync(path.join(OUT, 'firetv.marks.json'), JSON.stringify({ marks }, null, 1));
  if (stop) await stop();
  await ctx.close(); await browser.close();
  for (const f of fs.readdirSync(OUT)) if (f.startsWith('.ocr-')) fs.unlinkSync(path.join(OUT, f));
  console.log(marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
