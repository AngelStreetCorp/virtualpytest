// Video 25a (layouts). Storyboard, validated by the owner 2026-10-12:
// /home/jndoye/virtualpytest-promo/task82/storyboard-25a.md (copy of docs/tasks/video-storyboards/25a-layouts.md).
// Beats: 1 start view 24 | 2 menu pick 12 | 3 menu pick 48 + slow scroll | 4 Side by side | 5 Grid 2x2 |
// 6 One full | 7 click a stream: modal in big | 8 close the modal, back on One full. Cards 0 and 9 are in build2.py.
// Every beat: the menu pick is on camera (menu mark ~1 s before the View click, picked mark after the option click),
// the tile wait between picked and loaded is cut, then the label is asserted and the hold is filmed.
// Usage (codebox): PROMO_PROXY=socks5://127.0.0.1:18091 PROMO_BASE=https://virtualpytest.angelstreet.io node layouts_capture.js
//   -> raw25/layouts.mp4 + raw25/layouts.marks.json + raw25/take.log
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw25'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, glide, startRecorder, scrubSecrets } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const PROXY = process.env.PROMO_PROXY || null;
const PREFLIGHT = process.argv[2] === 'preflight';   // same setup and checks, no recorder, holds cut to 0.5 s
const hold = (page, ms) => page.waitForTimeout(PREFLIGHT ? 500 : ms);
const VPT_PI4 = /^(vpt-pi4|84\.97\.49\.52)$/;   // the picker shows the server by its IP until its name is known; curl: 84.97.49.52 is server_name vpt-pi4
const FILM_TITLES = [   // first four layout slots: real films (bipbop / test_001 / pts_shift streams are test patterns)
  'HLS Tears of Steel - vpt-nipogi', 'HLS Mux Big Buck Bunny - vpt-nipogi',
  'HLS ireplay Blender live low - vpt-nipogi', 'HLS THEO Big Buck Bunny - vpt-nipogi',
];

// The first `expected.length` layout slots (DeviceLayout data-slot order) must show these tile titles.
async function assertSlotTitles(page, expected, beatName) {
  const got = await page.evaluate(() => Array.from(document.querySelectorAll('[data-slot]'))
    .sort((a, b) => Number(a.getAttribute('data-slot')) - Number(b.getAttribute('data-slot')))
    .map(s => s.querySelector('h6[aria-label]')?.getAttribute('aria-label') ?? null));
  console.log(`beat ${beatName}: slot titles = ${JSON.stringify(got.slice(0, expected.length))}`);
  const ok = expected.every((t, i) => got[i] === t);
  if (!ok) throw new Error(`beat ${beatName}: layout slots ${JSON.stringify(got.slice(0, expected.length))} != ${JSON.stringify(expected)}`);
}

// Fail if the AI command bar is open (its input is the only element with this placeholder).
async function assertNoAi(page) {
  const open = await page.locator('input[placeholder^="Ask AI"]').first().isVisible().catch(() => false);
  if (open) throw new Error('AI command bar is open on the page');
}

// Fail if a dropdown is open: the Target filter list (its search box) or any listbox.
async function assertNoDropdown(page) {
  const open = await page.locator('input[placeholder="Search targets..."], [role="listbox"]').first().isVisible().catch(() => false);
  if (open) throw new Error('a dropdown is open on the page');
}

// Every visible stream tile must be a vpt-nipogi stream (the Target filter keeps only those).
async function assertNipogiOnly(page) {
  const titles = await page.evaluate(() => Array.from(document.querySelectorAll('h6[aria-label]'))
    .filter(e => e.getBoundingClientRect().width > 0).map(e => e.getAttribute('aria-label')));
  const bad = titles.filter(t => !/vpt-nipogi$/.test(t));
  console.log(`tiles on page: ${titles.length}, not vpt-nipogi: ${bad.length}`);
  if (titles.length === 0) throw new Error('no stream tiles on the page');
  if (bad.length) throw new Error(`tile(s) not from vpt-nipogi: ${JSON.stringify(bad.slice(0, 5))}`);
}

// Park the cursor on an empty area right of the filters (not on a tile, not on a nav item, never (30,860) = AI button).
async function parkCursor(page) {
  await page.mouse.move(1200, 110, { steps: 4 });
  await page.waitForTimeout(200);
}

// Playing check: visible tiles (img or video, inside the viewport). <img> loaded and not black (luminance > 20);
// <video> readyState >= 3 and currentTime advancing over 1 s. Needs min(minTiles, visible) OK, up to maxMs. Throws.
async function waitForTilesPlaying(page, minTiles = 4, maxMs = 25000) {
  const start = Date.now();
  const sample = () => page.evaluate(() => {
    const vh = window.innerHeight;
    const loading = Array.from(document.querySelectorAll('*')).filter(e => e.childElementCount === 0 && /Loading stream/.test(e.textContent) && e.getBoundingClientRect().width > 0).length;
    const media = Array.from(document.querySelectorAll('img, video')).filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 100 && r.top >= 0 && r.top < vh && r.left >= 0;
    }).map(el => {
      if (el.tagName === 'IMG') {
        let lum = -1;
        try {
          const c = document.createElement('canvas'); c.width = 40; c.height = 24;
          const ctx = c.getContext('2d'); ctx.drawImage(el, 0, 0, 40, 24);
          const d = ctx.getImageData(0, 0, 40, 24).data; let sum = 0;
          for (let i = 0; i < d.length; i += 4) sum += d[i] + d[i + 1] + d[i + 2];
          lum = Math.round(sum / (40 * 24 * 3));
        } catch (e) { /* tainted canvas: lum stays -1 */ }
        return { kind: 'img', ok: el.complete && el.naturalWidth > 0 && lum > 20, lum };
      }
      return { kind: 'video', rs: el.readyState, t: el.currentTime };
    });
    return { loading, media };
  });
  while (Date.now() - start < maxMs) {
    const first = (await sample()).media;
    await page.waitForTimeout(1000);
    const second = await sample();
    const media2 = second.media;
    let ok = 0;
    for (let i = 0; i < Math.min(first.length, media2.length); i++) {
      const a = first[i], b = media2[i];
      if (a.kind === 'img' && b.kind === 'img') { if (a.ok && b.ok) ok++; }
      else if (a.kind === 'video' && b.kind === 'video') { if (a.rs >= 3 && b.rs >= 3 && b.t > a.t + 0.05) ok++; }
    }
    console.log(`tiles: visible=${first.length} ok=${ok} loading=${second.loading} need>=${Math.min(minTiles, first.length)}`);
    if (first.length > 0 && ok >= Math.min(minTiles, first.length) && second.loading === 0) return true;
    await page.waitForTimeout(1000);
  }
  throw new Error(`tiles not playing: required >= ${minTiles} OK after ${maxMs}ms`);
}

// The View button label, e.g. "View 48 per page".
async function viewButtonLabel(page) {
  return (await page.locator('button[aria-haspopup="menu"]').filter({ hasText: 'View' }).first().innerText().catch(() => '')).replace(/\s+/g, ' ').trim();
}

async function assertViewLabel(page, expected, beatName) {
  const label = await viewButtonLabel(page);
  console.log(`beat ${beatName}: view button label = "${label}"`);
  if (!label.includes(expected)) throw new Error(`beat ${beatName}: expected View label "${expected}", got "${label}"`);
}

// Menu pick: glide to View (mark ~1 s before the click), click, popover stays open 1.5 s, glide to the option, click.
// isLayout: the option is the layout name; otherwise the grid page size (exact text inside the popover).
async function openViewMenuAndClick(page, optionText, isLayout, mk, tag) {
  const viewBtn = page.locator('button[aria-haspopup="menu"]').filter({ hasText: 'View' }).first();
  await page.keyboard.press('Escape'); await page.waitForTimeout(600);
  const vbb = await viewBtn.boundingBox();
  if (!vbb) throw new Error('View button not found');
  const vx = vbb.x + vbb.width / 2, vy = vbb.y + vbb.height / 2;
  if (mk) mk(`${tag}-menu`);
  await page.mouse.move(vx, vy, { steps: 12 });   // glide to View (~1 s)
  await page.waitForTimeout(1000);
  await assertNoAi(page);
  await page.mouse.click(vx, vy);
  const popover = page.locator('.MuiPopover-paper').filter({ hasText: 'fits the screen' }).last();
  let open = await popover.waitFor({ state: 'visible', timeout: 4000 }).then(() => true).catch(() => false);
  if (!open) {
    await viewBtn.click({ timeout: 5000 }).catch(() => {});
    open = await popover.waitFor({ state: 'visible', timeout: 4000 }).then(() => true).catch(() => false);
  }
  if (!open) throw new Error(`View menu popover did not open for "${optionText}"`);
  let opt;
  if (isLayout) {
    const re = new RegExp(`^\\s*${optionText.replace(/×/g, '[x×]')}\\s*$`);
    opt = popover.getByText(re).first();
  } else {
    opt = popover.getByText(optionText, { exact: true }).first();
  }
  if (!(await opt.isVisible().catch(() => false))) throw new Error(`option "${optionText}" not visible in View menu`);
  await page.waitForTimeout(1500);                // popover stays open 1.5 s, on camera
  const obb = await opt.boundingBox();
  const ox = obb.x + obb.width / 2, oy = obb.y + obb.height / 2;
  await page.mouse.move(ox, oy, { steps: 10 });
  if (mk) mk(`${tag}-picked`);   // the click instant: the layout reloads right after it (black or "Loading stream" tiles)
  await page.mouse.click(ox, oy);
  await page.waitForTimeout(1000);
  await page.keyboard.press('Escape').catch(() => {});
}

// Slow page scroll (smoothstep over ms) of the largest scrolling container, else the window. Returns how far it moved.
async function slowScroll(page, px, ms) {
  return page.evaluate(async ([px, ms]) => {
    const cands = Array.from(document.querySelectorAll('*')).filter(e => /(auto|scroll)/.test(getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 50);
    cands.sort((a, b) => b.clientHeight - a.clientHeight);
    const el = cands[0] || document.scrollingElement;
    const win = el === document.scrollingElement;
    const get = () => (win ? window.scrollY : el.scrollTop);
    const set = v => { if (win) window.scrollTo(0, v); else el.scrollTop = v; };
    const y0 = get(); const t0 = performance.now();
    await new Promise(res => {
      const step = now => {
        const f = Math.min(1, (now - t0) / ms);
        set(y0 + px * (f * f * (3 - 2 * f)));
        if (f < 1) requestAnimationFrame(step); else res();
      };
      requestAnimationFrame(step);
    });
    return { moved: get() - y0, on: win ? 'window' : `${el.tagName}.${String(el.className).slice(0, 40)}` };
  }, [px, ms]);
}

// Stream modal (RecHostStreamModal: a plain fixed Box, not a MUI dialog). Its header has "Take Screenshot" and
// "Open fullscreen player" and a Close IconButton (aria-label "Close", the last one in the DOM).
const modalClose = page => page.locator('button[aria-label="Close"]').last();
const modalOpen = page => page.locator('[aria-label="Take Screenshot"]').first().isVisible().catch(() => false);
// Playing = a video that is advancing (the tile under the modal is paused: "Playing in modal").
async function waitModalPlaying(page, maxMs = 45000) {
  const start = Date.now();
  const sample = () => page.evaluate(() => Array.from(document.querySelectorAll('video')).filter(v => v.getBoundingClientRect().width > 300).map(v => ({ rs: v.readyState, t: v.currentTime })));
  while (Date.now() - start < maxMs) {
    const a = await sample(); await page.waitForTimeout(1000); const b = await sample();
    const ok = a.some((x, i) => b[i] && x.rs >= 3 && b[i].rs >= 3 && b[i].t > x.t + 0.05);
    console.log(`modal video: ${JSON.stringify(b)} playing=${ok}`);
    if (ok) return true;
    await page.waitForTimeout(800);
  }
  throw new Error('modal stream not playing');
}

(async () => {
  const launchOpts = { headless: true };
  if (PROXY) launchOpts.proxy = { server: PROXY };
  const browser = await chromium.launch(launchOpts);
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  const logf = path.join(OUT, PREFLIGHT ? 'preflight.log' : 'take.log'); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  let stop = null; const marks = []; let t0 = Date.now();
  const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); log(`mark ${l} ${((Date.now() - t0) / 1000).toFixed(1)}`); };

  // Server pick + Target filter. Run again after the layout order is written (a reload re-reads it).
  const setupPage = async () => {
  // --- 1. Load + server pick (vpt-pi4), verified by device count ---
  await page.goto(url('/'), { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(2500);
  await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 });
  await page.waitForTimeout(10000);
  let serverOK = false;
  for (let attempt = 1; attempt <= 3 && !serverOK; attempt++) {
    log(`server pick attempt ${attempt}`);
    const ssb = await page.locator('.MuiSelect-select').first().boundingBox();
    await glide(page, ssb.x + ssb.width / 2, ssb.y + ssb.height / 2, 400);
    let pi4 = null;
    for (let t = 0; t < 30; t += 2) {
      const cands = page.locator('[role="option"]').filter({ hasText: VPT_PI4 });
      if (await cands.first().isVisible().catch(() => false)) { pi4 = cands.first(); break; }
      await page.waitForTimeout(2000);
    }
    if (!pi4) {
      log(`vpt-pi4 not visible, options: ${JSON.stringify(await page.locator('[role="option"]').allTextContents())}`);
      await page.keyboard.press('Escape'); await page.waitForTimeout(2000);
      continue;
    }
    await pi4.click();
    await page.waitForTimeout(5000);
    const serverLabel = (await page.locator('.MuiSelect-select').first().innerText()).trim();
    const bodyText = await page.locator('body').innerText();
    const dm = bodyText.match(/Device\s*\(?\s*(\d+)\s*\)?/i);
    const deviceCount = dm ? parseInt(dm[1]) : 0;
    log(`verify: server="${serverLabel}" deviceCount=${deviceCount}`);
    if (VPT_PI4.test(serverLabel) && deviceCount >= 24) serverOK = true;
    else { log(`verify FAILED: server="${serverLabel}" deviceCount=${deviceCount}`); await page.waitForTimeout(2000); }
  }
  if (!serverOK) throw new Error('server pick failed: vpt-pi4 not confirmed after 3 attempts');

  // --- 1b. Target filter: only the vpt-nipogi streams (vpt-windows offline removed) ---
  const targetIdx = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('.MuiSelect-select')).map((e, i) => ({ i, r: e.getBoundingClientRect() }));
    const c = els.filter(o => o.r.x > 450 && o.r.x < 800 && o.r.y > 80 && o.r.y < 180).sort((a, b) => a.r.x - b.r.x);
    return c.length ? c[0].i : -1;
  });
  if (targetIdx < 0) throw new Error('target filter select not found');
  const targetSelect = page.locator('.MuiSelect-select').nth(targetIdx);
  await targetSelect.scrollIntoViewIfNeeded().catch(() => {});
  const tsb = await targetSelect.boundingBox();
  await glide(page, tsb.x + tsb.width / 2, tsb.y + tsb.height / 2, 700);
  const search = page.locator('input[placeholder="Search targets..."]').first();
  if (!(await search.waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false))) throw new Error('Target dropdown did not open');
  const menu = page.locator('.MuiPopover-root, .MuiMenu-root').last();
  const clear = menu.getByText(/^Clear$/).first();
  if (await clear.isEnabled().catch(() => false)) await clear.click();
  await page.waitForTimeout(800);
  for (const host of ['vpt-nipogi']) {   // storyboard 25a: the 24 vpt-nipogi streams only (not vpt-pi4)
    await search.fill(''); await search.pressSequentially(host, { delay: 60 });
    await page.waitForTimeout(1000);
    const selAll = menu.getByText(/^Select all$/).first();
    if (!(await selAll.isVisible().catch(() => false))) throw new Error(`target filter: no "Select all" for ${host}`);
    await selAll.click();
    await page.waitForTimeout(500);
  }
  await page.mouse.click(640, 150);   // close on an empty header area (NOT (30,860): AI button)
  await page.waitForTimeout(1500);
  if (await search.isVisible().catch(() => false)) {   // the target list must be closed before the start view is filmed
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(800);
    await page.mouse.click(640, 150);
    await page.waitForTimeout(1500);
  }
  await assertNoDropdown(page);
  await page.waitForTimeout(1000);
  await assertNipogiOnly(page);
  };
  await setupPage();

  // Layout slots must show films, not the bipbop test pattern: write the saved slot order of the three layouts
  // off camera (the same localStorage entry that DeviceLayout's drag-swap writes), then reload and set up again.
  const keyOf = await page.evaluate((titles) => {
    const out = {};
    for (const t of titles) {
      const el = Array.from(document.querySelectorAll('[data-device-tile]')).find(e => e.querySelector(`h6[aria-label="${CSS.escape(t)}"]`));
      out[t] = el ? el.getAttribute('data-device-tile') : null;
    }
    return out;
  }, FILM_TITLES);
  const missing = FILM_TITLES.filter(t => !keyOf[t]);
  if (missing.length) {
    const avail = await page.evaluate(() => Array.from(document.querySelectorAll('h6[aria-label]')).map(e => e.getAttribute('aria-label')));
    throw new Error(`film tile(s) not on the page: ${JSON.stringify(missing)}; tiles: ${JSON.stringify(avail)}`);
  }
  const keys = FILM_TITLES.map(t => keyOf[t]);
  const want = { side: keys.slice(0, 2), grid2x2: keys.slice(0, 4), one: keys.slice(0, 1) };
  const stored = await page.evaluate(() => { try { return JSON.parse(localStorage.getItem('rec_filters_layoutOrder') || '{}'); } catch (e) { return {}; } });
  const sameOrder = Object.keys(want).every(id => JSON.stringify((stored[id] || []).slice(0, want[id].length)) === JSON.stringify(want[id]));
  if (!sameOrder) {
    await page.evaluate((m) => { localStorage.setItem('rec_filters_layoutOrder', JSON.stringify(m)); }, { ...stored, ...want });
    log(`layout order set: side, grid2x2, one start with the four films`);
    await setupPage();
  }

  // --- 2. Start view must be ready: 24 per page, tiles playing (fail closed) ---
  await waitForTilesPlaying(page, 8, 40000);
  await scrubSecrets(page);
  await page.waitForTimeout(2000);
  if (!PREFLIGHT) stop = await startRecorder(page, 'layouts');
  t0 = Date.now();

  // BEAT 1: start view, 24 per page, hold 3 s
  await parkCursor(page); await assertNoAi(page); await assertNoDropdown(page); await assertNipogiOnly(page);
  await assertViewLabel(page, '24 per page', '1');
  const n24 = await page.locator('h6[aria-label]').count();
  log(`beat 1: tiles on page = ${n24}`);
  if (n24 < 24) throw new Error(`beat 1: expected 24 tiles, got ${n24}`);
  await waitForTilesPlaying(page, 24, 30000);
  await assertViewLabel(page, '24 per page', '1');
  mark('beat1-loaded');
  await hold(page, 3000);
  await assertNoAi(page); mark('beat1-grid24');

  // BEAT 2: menu pick 12 per page, hold 3 s
  await openViewMenuAndClick(page, '12', false, mark, 'beat2');
  await waitForTilesPlaying(page, 1000, 40000);   // every visible tile playing before the hold
  await parkCursor(page); await assertNoAi(page);
  await assertViewLabel(page, '12 per page', '2');
  await scrubSecrets(page);
  mark('beat2-loaded');
  await hold(page, 3000);
  await assertViewLabel(page, '12 per page', '2'); mark('beat2-grid12');

  // BEAT 3: menu pick 48 per page, slow scroll about 2 s, hold 3 s
  await openViewMenuAndClick(page, '48', false, mark, 'beat3');
  await waitForTilesPlaying(page, 1000, 40000);   // every visible tile playing before the scroll and hold
  await parkCursor(page); await assertNoAi(page);
  await assertViewLabel(page, '48 per page', '3');
  await scrubSecrets(page);
  mark('beat3-loaded');
  const sc = await slowScroll(page, 500, 2000);
  log(`beat 3: scroll ${JSON.stringify(sc)}`);
  if (sc.moved < 100) throw new Error(`beat 3: page did not scroll (${JSON.stringify(sc)})`);
  await parkCursor(page);
  await hold(page, 3000);
  await assertViewLabel(page, '48 per page', '3'); await assertNoAi(page); mark('beat3-48');
  // back to the top, off camera (the next layout is laid out from the top of the page)
  await page.evaluate(() => {
    Array.from(document.querySelectorAll('*')).filter(e => /(auto|scroll)/.test(getComputedStyle(e).overflowY)).forEach(e => { e.scrollTop = 0; });
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(1000);

  // BEAT 4: menu pick Side by side, hold 3 s
  await openViewMenuAndClick(page, 'Side by side', true, mark, 'beat4');
  await waitForTilesPlaying(page, 2, 40000);
  await parkCursor(page); await assertNoAi(page);
  await assertViewLabel(page, 'Side by side', '4');
  await assertSlotTitles(page, FILM_TITLES.slice(0, 2), '4');
  await scrubSecrets(page);
  mark('beat4-loaded');
  await hold(page, 3000);
  await assertViewLabel(page, 'Side by side', '4'); mark('beat4-side');

  // BEAT 5: menu pick Grid 2×2, hold 3 s
  await openViewMenuAndClick(page, 'Grid 2×2', true, mark, 'beat5');
  await waitForTilesPlaying(page, 1000, 40000);   // all four slots playing before the hold
  await parkCursor(page); await assertNoAi(page);
  await assertViewLabel(page, 'Grid 2×2', '5');
  await assertSlotTitles(page, FILM_TITLES, '5');
  await scrubSecrets(page);
  mark('beat5-loaded');
  await hold(page, 3000);
  await assertViewLabel(page, 'Grid 2×2', '5'); mark('beat5-grid2x2');

  // BEAT 6: menu pick One full, hold 3 s
  await openViewMenuAndClick(page, 'One full', true, mark, 'beat6');
  await waitForTilesPlaying(page, 1, 40000);
  await parkCursor(page); await assertNoAi(page);
  await assertViewLabel(page, 'One full', '6');
  await assertSlotTitles(page, FILM_TITLES.slice(0, 1), '6');
  await scrubSecrets(page);
  mark('beat6-loaded');
  await hold(page, 3000);
  await assertViewLabel(page, 'One full', '6'); mark('beat6-one');

  // BEAT 7: click the stream: modal opens in big, hold 5 s with the stream playing
  const tc = await page.evaluate(() => {
    const e = Array.from(document.querySelectorAll('img, video')).filter(el => { const r = el.getBoundingClientRect(); return r.width > 300 && r.top >= 0 && r.top < innerHeight; })
      .sort((a, b) => b.getBoundingClientRect().width * b.getBoundingClientRect().height - a.getBoundingClientRect().width * a.getBoundingClientRect().height)[0];
    if (!e) return null; const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2];
  });
  if (!tc) throw new Error('beat 7: no stream tile to click');
  mark('beat7-click');
  await page.mouse.move(tc[0], tc[1], { steps: 12 });
  await page.waitForTimeout(800);
  await page.mouse.click(tc[0], tc[1]);
  const openDeadline = Date.now() + 20000;
  while (!(await modalOpen(page)) && Date.now() < openDeadline) await page.waitForTimeout(500);
  if (!(await modalOpen(page))) {
    const labels = await page.evaluate(() => Array.from(document.querySelectorAll('[aria-label]')).map(e => e.getAttribute('aria-label')).slice(0, 80));
    await page.screenshot({ path: path.join(OUT, 'beat7-fail.png') });
    log(`beat 7: modal did not open; aria-labels=${JSON.stringify(labels)}`);
    throw new Error('beat 7: modal did not open');
  }
  await waitModalPlaying(page, 45000);
  mark('beat7-open');
  await parkCursor(page);
  await assertNoAi(page);
  if (!(await modalOpen(page))) throw new Error('beat 7: modal not open at hold');
  mark('beat7-loaded');
  await hold(page, 5000);
  if (!(await modalOpen(page))) throw new Error('beat 7: modal closed during hold');
  mark('beat7-end');

  // BEAT 8: close the modal with its close button, back on One full, hold 5 s
  mark('beat8-click');
  const cb = await modalClose(page).boundingBox();
  await page.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2, { steps: 12 });
  await page.waitForTimeout(600);
  await page.mouse.click(cb.x + cb.width / 2, cb.y + cb.height / 2);
  const closeDeadline = Date.now() + 15000;
  while (await modalOpen(page) && Date.now() < closeDeadline) await page.waitForTimeout(300);
  if (await modalOpen(page)) throw new Error('beat 8: modal did not close');
  mark('beat8-closed');
  await waitForTilesPlaying(page, 1, 40000);
  await parkCursor(page); await assertNoAi(page);
  if (await modalOpen(page)) throw new Error('beat 8: modal still open');
  await assertViewLabel(page, 'One full', '8');
  await assertSlotTitles(page, FILM_TITLES.slice(0, 1), '8');
  await scrubSecrets(page);
  mark('beat8-loaded');
  await hold(page, 5000);
  await assertViewLabel(page, 'One full', '8'); await assertNoAi(page); mark('beat8-end');

  log('done');
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!PREFLIGHT) fs.writeFileSync(path.join(OUT, 'layouts.marks.json'), JSON.stringify({ marks }, null, 1));
})().catch(e => {
  console.log('FATAL', String(e.message || e).slice(0, 300));
  process.exit(1);
});
