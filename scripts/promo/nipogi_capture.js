// Video 15: 24 streams on one host. rpitest Device page, the 24 vpt-nipogi streams selected in the Target filter
// (off camera: the page prunes saved filters while its list loads, so they are picked in the dropdown), then the
// grid scrolled, narrowed to a few, one stream opened (HD) and its A/V quality page. View only, nothing driven.
// Usage: node nipogi_capture.js scout -> raw15/scout-*.png ; node nipogi_capture.js -> raw15/nipogi.mp4 + nipogi.marks.json
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw15'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, relay, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const HOST = 'vpt-nipogi';
const FEW = (process.env.FEW || 'HLS Mux Big Buck Bunny,HLS Tears of Steel,HLS Shaka live,HLS ireplay Blender live low').split(',');
const OPEN = process.env.OPEN || 'HLS Tears of Steel';

const center = async loc => { const b = await loc.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; };
// the Target filter: the select showing "All Targets" or the picked targets (not the Server select in the header)
const targetSelect = page => page.locator('.MuiSelect-select').nth(1);   // 0 = the Server select in the header

// the Target dropdown has a search box and "Select all" / "Clear" for the visible (searched) options
async function openTargets(page) {
  const box = page.locator('input[placeholder="Search targets..."]').first();
  for (let attempt = 1; attempt <= 4; attempt++) {
    await targetSelect(page).scrollIntoViewIfNeeded().catch(() => {});
    await glide(page, ...(await center(targetSelect(page))), 700);
    if (await box.waitFor({ timeout: 4000 }).then(() => true).catch(() => false)) return;
    await page.keyboard.press('Escape'); await page.waitForTimeout(800);
  }
  throw new Error('Target dropdown did not open');
}
async function search(page, text) {
  const box = page.locator('input[placeholder="Search targets..."]').first();
  for (let attempt = 1; attempt <= 3; attempt++) {
    if (!(await box.isVisible().catch(() => false))) await openTargets(page);   // the menu closed on its own: reopen
    await page.waitForTimeout(400);
    const ok = await box.fill('', { timeout: 5000 }).then(() => box.pressSequentially(text, { delay: 60, timeout: 8000 })).then(() => true).catch(() => false);
    if (ok) { await page.waitForTimeout(700); return; }
  }
  throw new Error(`could not search "${text}"`);
}
// Escape does not close the menu while its search box has focus: click the backdrop
async function closeMenu(page) {
  const bd = page.locator('.MuiBackdrop-root, .MuiPopover-root > div:first-child').first();
  if (await bd.isVisible().catch(() => false)) await page.mouse.click(30, 860); else await page.keyboard.press('Escape');
  await page.waitForTimeout(900);
}
const menuButton = (page, name) => page.locator('.MuiPopover-root, .MuiMenu-root').last().getByText(new RegExp(`^${name}$`)).first();

async function walk(page, mark, shot, log, startRec) {
  await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 });
  // rpitest's tunnel drops now and then: a page loaded while it was down shows Device (0) and stays so; reload
  for (let attempt = 1; ; attempt++) {
    if (await page.locator(`text=/ - ${HOST}$/`).first().waitFor({ timeout: 40000 }).then(() => true).catch(() => false)) break;
    if (attempt >= 4) throw new Error(`no ${HOST} device listed (server offline?)`);
    log(`no ${HOST} tile, reload (attempt ${attempt})`); await page.reload({ waitUntil: 'load', timeout: 120000 });
  }
  await page.waitForTimeout(4000);
  // the 24 streams of the one host: search the host name, Select all (recorded: this is the point of the video)
  await page.mouse.move(800, 300); await page.waitForTimeout(25000);   // tiles load
  await openTargets(page); await search(page, HOST); mark('search'); await shot('search');
  await glide(page, ...(await center(menuButton(page, 'Select all'))), 600);
  await closeMenu(page);
  // recording starts on Device (24): the unfiltered page shows other hosts' content (third-party posters)
  await page.waitForFunction(() => /Device \(24\)/.test(document.body.innerText), null, { timeout: 30000 }).catch(() => log('count is not 24'));
  await page.mouse.move(800, 300); await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(12000);   // tiles load
  await startRec(); mark('grid'); await shot('grid'); await page.waitForTimeout(3000);
  // scroll through the 24, then back to the top
  for (let y = 0; y < 6; y++) { await page.mouse.wheel(0, 260); await page.waitForTimeout(900); }
  mark('scrolled'); await shot('scrolled');
  for (let y = 0; y < 6; y++) { await page.mouse.wheel(0, -400); await page.waitForTimeout(250); }
  await page.evaluate(() => { window.scrollTo(0, 0); document.scrollingElement && (document.scrollingElement.scrollTop = 0); }); await page.waitForTimeout(1500);
  // narrow to a few, on camera: Clear, then search and tick each
  await openTargets(page); await search(page, HOST); await glide(page, ...(await center(menuButton(page, 'Clear'))), 500);
  for (const name of FEW) {
    await search(page, name);
    const o = page.locator('[role="option"]').filter({ hasText: new RegExp(`^${name} - ${HOST}$`) }).first();
    await glide(page, ...(await center(o)), 400);
  }
  await closeMenu(page);
  await page.mouse.move(800, 600, { steps: 15 }); await page.waitForTimeout(12000); mark('few'); await shot('few');
  // open one stream (its tile), HD
  const tile = page.locator(`text=/^${OPEN} - ${HOST}$/`).first();
  await glide(page, ...(await center(tile)).map((v, i) => i ? v + 120 : v), 700); await page.waitForTimeout(4000);
  const hd = page.locator('[aria-label="High definition"], button:has-text("HD")').first();
  if (await hd.isVisible().catch(() => false)) { await glide(page, ...(await center(hd)), 400); }
  await page.waitForTimeout(16000); mark('stream'); await shot('stream');
  // its A/V quality: close the modal, the tile's Audio/Video Quality icon
  await page.keyboard.press('Escape'); await page.waitForTimeout(1500);
  const close = page.locator('[aria-label="close"], button:has(svg[data-testid="CloseIcon"])').first();
  if (await close.isVisible().catch(() => false)) { await close.click().catch(() => {}); await page.waitForTimeout(1200); }
  const card = page.locator('.MuiCard-root, .MuiPaper-root').filter({ hasText: new RegExp(`^${OPEN} - ${HOST}`) }).first();
  const avq = card.getByRole('button', { name: 'Audio/Video Quality' }).first();
  await glide(page, ...(await center(avq)), 700); mark('avq-click');
  await page.getByText(/Last 24h \(/).first().waitFor({ timeout: 60000 }).catch(() => log('AVQ page did not show Last 24h'));
  await page.mouse.move(900, 300, { steps: 20 }); await page.waitForTimeout(14000); mark('avq'); await shot('avq');
  await page.waitForTimeout(1500); mark('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await relay(ctx); const page = await ctx.newPage();
  let stop = null; const marks = []; let t0 = Date.now();
  const startRec = async () => { if (!scout) stop = await startRecorder(page, 'nipogi'); t0 = Date.now(); };
  const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  const logf = path.join(OUT, `${scout ? 'scout' : 'take'}.log`); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-${name}.png`) });
  try { await walk(page, mark, shot, log, startRec); }
  catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'nipogi.marks.json'), JSON.stringify({ marks }, null, 1));
})();
