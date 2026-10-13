// Video 25b (group control). Storyboard v5, validated by the owner 2026-10-12 (Chrome, type once, scroll both):
// docs/tasks/video-storyboards/25b-group-control.md. Beats: 1 two tiles live | 2 group button | 3 tick S21x + S7 |
// 4 group view, one remote | 5 Home on both | 6 Chrome from the app list | 7 type virtualpytest.com once, Enter |
// 8 Scr↓ twice | 9 Home + Release. Cards 0 and 10 are in build2.py.
// Usage: node group_capture.js preflight   (the same walk, no recorder, holds cut to 0.5 s)
//        node group_capture.js             -> raw25/group.mp4 + raw25/group.marks.json + raw25/group_take.log
// Every control command goes through the group remote; control is released in a finally block.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw25'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, glide, startRecorder, scrubSecrets } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const PROXY = process.env.PROMO_PROXY || null;
const PREFLIGHT = process.argv[2] === 'preflight';
const hold = (page, ms) => page.waitForTimeout(PREFLIGHT ? 500 : ms);
const TILES = [{ name: /S21x/, host: /vpt-pi1/, label: 'S21x' }, { name: /^S7\b/, host: /vpt-mf1/, label: 'S7' }];
const BANNED = /Honor|set-top|stb\d|appletv|\bmi\b/i;
const CHROME_PKG = 'com.android.chrome';
const ADDRESS = 'virtualpytest.com';
const BLANK_TAB = 'about:blank';   // the address bar's text on Chrome's fresh tab (LAUNCH_APP shows it on both phones)
// Promo-only: the auto-sign test login's badge on the stream tiles is a debug label; hidden in the capture, never in the app.
const HIDE_BADGE = `setInterval(() => { for (const el of document.querySelectorAll('body *')) { if (el.children.length || el.textContent.trim() !== 'Auto Signed') continue; let b = el; while (b.parentElement && b.parentElement.textContent.trim() === 'Auto Signed') b = b.parentElement; b.style.setProperty('display', 'none', 'important'); } }, 300);`;

// Promo-only: the page header's job counter ("0% · 1 running · 0 passed · 0 failed") is hidden; its OCR reads "failed" and it is not part of the story.
const HIDE_PROGRESS = `setInterval(() => { const re = /\\d+ running · \\d+ passed · \\d+ failed/; for (const el of document.querySelectorAll('body *')) { if (!re.test(el.textContent)) continue; if ([...el.children].some(c => re.test(c.textContent))) continue; el.style.setProperty('visibility', 'hidden', 'important'); } }, 300);`;

// Live tiles of the two phones: [data-device-tile] elements whose text matches, visible.
async function tileInfo(page, re) {
  return page.evaluate((src) => {
    const r = new RegExp(src);
    const els = Array.from(document.querySelectorAll('[data-device-tile]')).filter(e => r.test(e.textContent) && e.getBoundingClientRect().width > 0);
    if (!els.length) return null;
    const e = els[0]; const b = e.getBoundingClientRect(); const cb = e.querySelector('input[type="checkbox"]');
    const cbb = cb ? cb.getBoundingClientRect() : null;
    return { n: els.length, x: b.x + b.width / 2, y: b.y + b.height / 2, cb: cbb ? { x: cbb.x + cbb.width / 2, y: cbb.y + cbb.height / 2 } : null };
  }, re.source);
}

// Pixel signature of every visible stream in the viewport (img or video, drawn to a 40x24 canvas): null when tainted.
// The group view shows each phone as a live <video> or as a 1 Hz snapshot <img> (TASK-48), both inside the modal.
const STREAM_SEL = 'video, img[alt$="snapshot"]';
const sigs = page => page.evaluate((sel) => { const root = document.querySelector('[role="dialog"]') || document; return (Array.from(root.querySelectorAll(sel)).filter(el => { const r = el.getBoundingClientRect(); if (r.width <= 150 || r.top < 0 || r.top >= innerHeight || r.left < 0) return false; return el.tagName === 'IMG' ? (el.complete && el.naturalWidth > 0) : el.readyState >= 2; })).map(el => {
  try {
    const c = document.createElement('canvas'); c.width = 40; c.height = 24; const ctx = c.getContext('2d');
    ctx.drawImage(el, 0, 0, 40, 24); return Array.from(ctx.getImageData(0, 0, 40, 24).data).filter((_, i) => i % 16 === 0);
  } catch (e) { return null; }
}); }, STREAM_SEL);

// Live streams never repeat a pixel exactly, so a change is a mean difference over the signature that holds for two samples.
const CHANGE_T = 10;
const meanDiff = (a, b) => a.reduce((s, v, i) => s + Math.abs(v - b[i]), 0) / a.length;

// Waits until both phones' streams changed from `before` (a key reached both screens); returns ms per stream (null = not seen), peak differences in .peaks.
async function timeToChange(page, before, maxMs = 12000) {
  const t0 = Date.now(); const done = before.map(() => null); const run = before.map(() => 0); const peaks = before.map(() => 0);
  while (Date.now() - t0 < maxMs && done.some(d => d === null)) {
    const now = await sigs(page);
    before.forEach((b, i) => {
      if (done[i] !== null || !now[i] || !b) return;
      const d = meanDiff(now[i], b); peaks[i] = Math.max(peaks[i], d);
      run[i] = d > CHANGE_T ? run[i] + 1 : 0;
      if (run[i] >= 2) done[i] = Date.now() - t0;
    });
    await page.waitForTimeout(150);
  }
  return Object.assign(done, { peaks: peaks.map(p => Math.round(p)) });
}

async function waitStreamsPlaying(page, n, maxMs) {
  const start = Date.now();
  const probe = () => page.evaluate((sel) => { const root = document.querySelector('[role="dialog"]') || document; return Array.from(root.querySelectorAll(sel)).filter(v => v.getBoundingClientRect().width > 150).map(v => v.tagName === 'IMG' ? { img: v.complete && v.naturalWidth > 0 } : { rs: v.readyState, t: v.currentTime }); }, STREAM_SEL);
  while (Date.now() - start < maxMs) {
    const a = await probe();
    await page.waitForTimeout(1000);
    const b = await probe();
    const ok = b.filter((x, i) => (x.img && a[i] && a[i].img) || (x.t !== undefined && a[i] && a[i].t !== undefined && x.t > a[i].t + 0.05)).length;
    console.log(`streams playing: ${ok}/${n}`);
    if (ok >= n) return true;
    await page.waitForTimeout(800);
  }
  const st = await page.evaluate(() => Array.from(document.querySelectorAll('*')).map(v => { const r = v.getBoundingClientRect(); const bg = getComputedStyle(v).backgroundImage; return { tag: v.tagName, w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x), y: Math.round(r.y), cls: String(v.className && v.className.baseVal === undefined ? v.className : '').slice(0, 50), bg: bg && bg !== 'none' ? bg.slice(0, 50) : '', dlg: !!v.closest('[role="dialog"]') }; }).filter(o => o.w > 200 && o.h > 300 && (o.dlg || o.bg)).slice(0, 25));
  console.log(`video state at timeout: ${JSON.stringify(st)}`);
  await page.screenshot({ path: path.join(OUT, 'stream-timeout.png') }).catch(() => {});
  throw new Error(`streams not playing: need ${n} within ${maxMs} ms`);
}

// Group view opened again after a stream stall: group button, tick each phone that is not ticked yet, Control 2 devices.
async function reopenGroupView(page, log) {
  const gb = await page.locator('[data-testid="DashboardIcon"]').first().locator('xpath=ancestor::button[1]').boundingBox();
  if (!gb) throw new Error('reopen: group control button not found');
  await page.mouse.click(gb.x + gb.width / 2, gb.y + gb.height / 2);
  await page.getByRole('button', { name: 'Clear' }).first().waitFor({ timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(1200);
  for (const t of TILES) {
    const ti = await tileInfo(page, t.name);
    if (!ti) throw new Error(`reopen: tile ${t.label} not found`);
    const checked = await page.evaluate((re) => { const r = new RegExp(re); const e = Array.from(document.querySelectorAll('[data-device-tile]')).find(x => r.test(x.textContent)); const cb = e && e.querySelector('input[type="checkbox"]'); return !!(cb && cb.checked); }, t.name.source);
    if (!checked) { const c = ti.cb || { x: ti.x, y: ti.y }; await page.mouse.click(c.x, c.y); await page.waitForTimeout(900); }
  }
  const ctrl = page.getByRole('button', { name: /Control 2 devices/ }).first();
  const cb2 = await ctrl.boundingBox(); if (!cb2) throw new Error('reopen: Control 2 devices button not found');
  await page.mouse.click(cb2.x + cb2.width / 2, cb2.y + cb2.height / 2);
  await page.getByRole('button', { name: 'Release all' }).waitFor({ timeout: 60000 });
  log('group view reopened');
}

// Target filter: only the two phones. Clear first, then pick each phone's option by its name.
async function setTargets(page) {
  const idx = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('.MuiSelect-select')).map((e, i) => ({ i, r: e.getBoundingClientRect() }));
    const c = els.filter(o => o.r.x > 450 && o.r.x < 800 && o.r.y > 80 && o.r.y < 180).sort((a, b) => a.r.x - b.r.x);
    return c.length ? c[0].i : -1;
  });
  if (idx < 0) throw new Error('target filter select not found');
  const sel = page.locator('.MuiSelect-select').nth(idx);
  const sb = await sel.boundingBox();
  await glide(page, sb.x + sb.width / 2, sb.y + sb.height / 2, 600);
  const search = page.locator('input[placeholder="Search targets..."]').first();
  if (!(await search.waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false))) throw new Error('Target dropdown did not open');
  const menu = page.locator('.MuiPopover-root, .MuiMenu-root').last();
  const clear = menu.getByText(/^Clear$/).first();
  if (await clear.isEnabled().catch(() => false)) await clear.click();
  await page.waitForTimeout(600);
  for (const t of TILES) {
    await search.fill(''); await search.pressSequentially(t.label, { delay: 60 });
    await page.waitForTimeout(800);
    const opts = menu.locator('[role="option"]');
    const texts = await opts.allTextContents();
    console.log(`target options for "${t.label}": ${JSON.stringify(texts.map(s => s.replace(/\s+/g, ' ').trim()).slice(0, 12))}`);
    const pick = opts.filter({ hasText: t.name }).filter({ hasText: t.host }).first();
    if (!(await pick.isVisible().catch(() => false))) throw new Error(`target option for ${t.label} not visible`);
    await pick.click(); await page.waitForTimeout(500);
  }
  await page.mouse.click(640, 150); await page.waitForTimeout(1200);
  if (await search.isVisible().catch(() => false)) { await page.keyboard.press('Escape').catch(() => {}); await page.waitForTimeout(800); }
}

// Element Interaction on the group remote: Click by Text with each candidate until the phones report ✓.
async function clickByText(page, texts, log) {
  const etype = page.locator('.MuiFormControl-root', { has: page.locator('.MuiSelect-select', { hasText: /Click by ID|Click by Text|Find Element/ }) }).locator('.MuiSelect-select').first();
  await etype.click(); await page.waitForTimeout(500);
  await page.getByRole('option', { name: 'Click by Text' }).click(); await page.waitForTimeout(400);
  const field = page.locator('input[placeholder="Element text"]').first();
  for (const t of texts) {
    await field.fill(t);
    await page.waitForTimeout(300);
    const cl = page.getByRole('button', { name: /^(✓ |✗ )?Click$/ }).first();
    const cb = await cl.boundingBox(); if (!cb) throw new Error('Click button not found');
    await page.mouse.move(cb.x + cb.width / 2, cb.y + cb.height / 2, { steps: 10 }); await page.waitForTimeout(300);
    await page.mouse.click(cb.x + cb.width / 2, cb.y + cb.height / 2);
    await page.waitForTimeout(2500);
    const label = (await cl.innerText().catch(() => '')).trim();
    log(`click by text "${t}": button "${label}"`);
    if (label.includes('✓')) return t;
  }
  return null;
}

// The group remote's App Launcher is empty until its app list loads; the refresh button beside it reloads it.
async function ensureApps(page, log) {
  const count = () => page.getByText(/App Launcher \(\d+ apps?\)/).first().innerText().then(t => Number((t.match(/\((\d+)/) || [])[1] || 0)).catch(() => 0);
  for (let attempt = 1; attempt <= 3; attempt++) {
    const deadline = Date.now() + 25000;
    while (Date.now() < deadline) { if ((await count()) > 0) { log(`app launcher: ${await count()} apps`); return true; } await page.waitForTimeout(1000); }
    const refresh = page.getByRole('button', { name: 'Refresh apps' }).first();
    if (!(await refresh.isVisible().catch(() => false))) break;
    log(`app launcher empty, refresh attempt ${attempt}`);
    await refresh.click().catch(() => {});
  }
  log(`app launcher still empty: ${await count()}`);
  return (await count()) > 0;
}

(async () => {
  const launchOpts = { headless: true };
  if (PROXY) launchOpts.proxy = { server: PROXY };
  const browser = await chromium.launch(launchOpts);
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR);
  await ctx.addInitScript(HIDE_BADGE);
  await ctx.addInitScript(HIDE_PROGRESS);
  const page = await ctx.newPage();
  const logf = path.join(OUT, PREFLIGHT ? 'group_preflight.log' : 'group_take.log'); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${PREFLIGHT ? 'pf' : 'take'}-${name}.png`) }).catch(() => {});
  let stop = null; const marks = []; let t0 = Date.now();
  const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); log(`mark ${l} ${((Date.now() - t0) / 1000).toFixed(1)}`); };
  const keyDelays = [];
  // Fixed wait after each on-camera action (the S7 trails by 5-7 s); the measured change is logged, never gated.
  const SETTLE_MS = 8000;
  const afterAction = async (label, before) => {
    const t = Date.now();
    const d = await timeToChange(page, before, SETTLE_MS);
    keyDelays.push({ label, ms: d });
    log(`key ${label}: change after ms ${JSON.stringify(d)} peak ${JSON.stringify(d.peaks)}`);
    await page.waitForTimeout(Math.max(0, SETTLE_MS - (Date.now() - t)));
  };

  try {
    // --- setup: server vpt-pi1, Device page, two phones only ---
    await page.goto(url('/'), { waitUntil: 'load', timeout: 120000 });
    await page.waitForTimeout(2500);
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 });
    await page.waitForTimeout(10000);
    let serverOK = false;
    for (let attempt = 1; attempt <= 3 && !serverOK; attempt++) {
      log(`server pick attempt ${attempt}`);
      const ssb = await page.locator('.MuiSelect-select').first().boundingBox();
      await glide(page, ssb.x + ssb.width / 2, ssb.y + ssb.height / 2, 400);
      const cands = page.locator('[role="option"]').filter({ hasText: /vpt-pi1/ });
      let found = false;
      for (let t = 0; t < 30; t += 2) { if (await cands.first().isVisible().catch(() => false)) { found = true; break; } await page.waitForTimeout(2000); }
      if (!found) { log(`vpt-pi1 not visible, options: ${JSON.stringify(await page.locator('[role="option"]').allTextContents())}`); await page.keyboard.press('Escape'); await page.waitForTimeout(2000); continue; }
      await cands.first().click(); await page.waitForTimeout(5000);
      const label = (await page.locator('.MuiSelect-select').first().innerText()).trim();
      log(`server="${label}"`);
      if (/vpt-pi1/.test(label)) serverOK = true;
    }
    if (!serverOK) throw new Error('server pick failed: vpt-pi1 not confirmed');
    await setTargets(page);
    await page.waitForTimeout(1500);
    await scrubSecrets(page);
    const tileNames = await page.evaluate(() => Array.from(document.querySelectorAll('[data-device-tile]')).map(e => (e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)));
    log(`tiles on page: ${JSON.stringify(tileNames)}`);
    if (tileNames.length !== 2) throw new Error(`expected 2 phone tiles, got ${tileNames.length}`);
    if (tileNames.some(t => BANNED.test(t))) throw new Error(`a banned device is on screen: ${JSON.stringify(tileNames)}`);
    for (const t of TILES) if (!(await tileInfo(page, t.name))) throw new Error(`tile ${t.label} not on the page`);
    await waitStreamsPlaying(page, 2, 90000);
    await shot('beat1');
    const n1 = await sigs(page); await page.waitForTimeout(1000); const n2 = await sigs(page);
    log(`noise, mean difference over 1 s per stream: ${JSON.stringify(n1.map((a, i) => (a && n2[i] ? Math.round(meanDiff(a, n2[i]) * 10) / 10 : null)))}`);
    if (!PREFLIGHT) stop = await startRecorder(page, 'group');
    t0 = Date.now();

    // BEAT 1: two tiles live, hold 3 s
    mark('beat1-start'); await hold(page, 3000); mark('beat1-end');

    // BEAT 2: group control button (dashboard icon, left of the edit pencil), hold 3 s
    const gb = await page.locator('[data-testid="DashboardIcon"]').first().locator('xpath=ancestor::button[1]').boundingBox();
    if (!gb) throw new Error('group control button not found');
    mark('beat2-action');
    await page.mouse.move(gb.x + gb.width / 2, gb.y + gb.height / 2, { steps: 20 }); await page.waitForTimeout(600);
    await page.mouse.click(gb.x + gb.width / 2, gb.y + gb.height / 2);
    await page.getByRole('button', { name: 'Clear' }).first().waitFor({ timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1200);
    mark('beat2-loaded'); await hold(page, 3000); mark('beat2-end');

    // BEAT 3: tick S21x, then S7 (each tile's checkbox), hold 3 s
    for (const t of TILES) {
      const ti = await tileInfo(page, t.name);
      if (!ti) throw new Error(`tile ${t.label} not found`);
      const c = ti.cb || { x: ti.x, y: ti.y };
      mark(`beat3-${t.label}-action`);
      await page.mouse.move(c.x, c.y, { steps: 14 }); await page.waitForTimeout(500);
      await page.mouse.click(c.x, c.y); await page.waitForTimeout(900);
    }
    const bar = await page.getByText(/Control 2 devices/).first().isVisible().catch(() => false);
    log(`bar "Control 2 devices" visible: ${bar}`);
    if (!bar) throw new Error('beat 3: "Control 2 devices" not on the bar');
    mark('beat3-loaded'); await hold(page, 3000); mark('beat3-end');

    // BEAT 4: Control 2 devices -> group view, 2 streams + one remote, hold 3 s
    const ctrl = page.getByRole('button', { name: /Control 2 devices/ }).first();
    const cb2 = await ctrl.boundingBox(); if (!cb2) throw new Error('Control 2 devices button not found');
    mark('beat4-action');
    await page.mouse.move(cb2.x + cb2.width / 2, cb2.y + cb2.height / 2, { steps: 16 }); await page.waitForTimeout(600);
    await page.mouse.click(cb2.x + cb2.width / 2, cb2.y + cb2.height / 2);
    await page.getByRole('button', { name: 'Release all' }).waitFor({ timeout: 60000 });
    try {
      await waitStreamsPlaying(page, 2, 90000);
    } catch (e) {
      log(`stream stall at the group view (${e.message}): closing and reopening the group view once`);
      await page.getByRole('button', { name: 'Release all' }).first().click();
      await page.waitForTimeout(2500);
      await reopenGroupView(page, log);
      await waitStreamsPlaying(page, 2, 90000);
    }
    await scrubSecrets(page);
    // the remote's new controls must be live before anything is pressed (storyboard preflight 1)
    for (const re of [/^Scr↑$/, /^Scr↓$/, /^Scr←$/, /^Scr→$/]) {
      if (!(await page.getByRole('button', { name: re }).first().isVisible().catch(() => false))) throw new Error(`remote control ${re} not on the group remote`);
    }
    if (!(await page.locator('input[placeholder="Type text"]').first().isVisible().catch(() => false))) throw new Error('Type text field not on the group remote');
    log('group remote: Type text, Enter, Scr↑ Scr↓ Scr← Scr→ visible');
    await shot('beat4');
    mark('beat4-loaded'); await hold(page, 3000); mark('beat4-end');
    // Off camera (the build cuts this gap): the group remote's app list loads on its own refresh.
    const appsReady = await ensureApps(page, log);
    if (!appsReady) throw new Error('app list did not load on the group remote (App Launcher has 0 apps)');

    // BEAT 5: press Home on the remote, both phones move, hold 3 s
    const home = page.locator('button').filter({ hasText: /^Home$/ }).last();
    const hb = await home.boundingBox(); if (!hb) throw new Error('Home button not found');
    mark('beat5-action');
    const before5 = await sigs(page);
    log(`stream signatures before home: ${before5.map(x => (x === null ? 'unreadable' : 'readable')).join(',') || 'none'}`);
    await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2, { steps: 14 }); await page.waitForTimeout(500);
    await page.mouse.click(hb.x + hb.width / 2, hb.y + hb.height / 2);
    await afterAction('home', before5);
    mark('beat5-loaded'); await hold(page, 3000); mark('beat5-end');
    await shot('beat5');

    // BEAT 6: Chrome from the app list (package com.android.chrome), hold 3 s after it has opened
    const appSel = page.locator('.MuiFormControl-root', { has: page.locator('label', { hasText: /Select an app/ }) }).locator('.MuiSelect-select').first();
    const asb = await appSel.boundingBox(); if (!asb) throw new Error('app launcher not found');
    mark('beat6-action');
    await page.mouse.move(asb.x + asb.width / 2, asb.y + asb.height / 2, { steps: 16 }); await page.waitForTimeout(600);
    await page.mouse.click(asb.x + asb.width / 2, asb.y + asb.height / 2); await page.waitForTimeout(800);
    const chrome = page.locator(`[role="option"][data-value="${CHROME_PKG}"]`).or(page.getByRole('option', { name: /^Chrome$/ })).first();
    if (!(await chrome.isVisible().catch(() => false))) {
      const opts = await page.getByRole('option').allTextContents();
      throw new Error(`app Chrome (${CHROME_PKG}) not in the app launcher list: ${JSON.stringify(opts)}`);
    }
    const before6 = await sigs(page);
    await chrome.click();
    await afterAction('chrome', before6);
    await shot('beat6');
    mark('beat6-loaded'); await hold(page, 3000); mark('beat6-end');

    // Off camera: the address bar takes focus (Click by Text on the blank tab's "about:blank"), so beat 7 types into it
    const focused = await clickByText(page, [BLANK_TAB, ADDRESS], log);
    if (!focused) { await shot('focus-fail'); throw new Error('BLOCKED: address bar not focused by Click by Text "about:blank" or "virtualpytest.com" (see take-focus-fail.png)'); }
    log(`address bar focused with "${focused}"`);
    await page.waitForTimeout(1200);

    // BEAT 7: click the remote's text field, type virtualpytest.com once, click Enter, hold 4 s after the page loads
    const tf = page.locator('input[placeholder="Type text"]').first();
    const tfb = await tf.boundingBox(); if (!tfb) throw new Error('Type text field not found');
    mark('beat7-action');
    await page.mouse.move(tfb.x + tfb.width / 2, tfb.y + tfb.height / 2, { steps: 14 }); await page.waitForTimeout(500);
    await page.mouse.click(tfb.x + tfb.width / 2, tfb.y + tfb.height / 2); await page.waitForTimeout(400);
    await tf.fill(''); await tf.pressSequentially(ADDRESS, { delay: 60 });
    await page.waitForTimeout(4000);
    mark('beat7-typed');
    const enter = page.getByRole('button', { name: /^Enter$/ }).first();
    const eb = await enter.boundingBox(); if (!eb) throw new Error('Enter button not found');
    const before7 = await sigs(page);
    await page.mouse.move(eb.x + eb.width / 2, eb.y + eb.height / 2, { steps: 12 }); await page.waitForTimeout(500);
    await page.mouse.click(eb.x + eb.width / 2, eb.y + eb.height / 2);
    mark('beat7-entered');
    await afterAction('enter', before7);
    await scrubSecrets(page);
    await shot('beat7');
    mark('beat7-loaded'); await hold(page, 3000); mark('beat7-end');

    // BEAT 8: Scr↓ twice, one click each; wait until both screens move, hold 3 s after each
    const sc = page.getByRole('button', { name: /^Scr↓$/ }).first();
    for (const k of [1, 2]) {
      const sb = await sc.boundingBox(); if (!sb) throw new Error('Scr↓ button not found');
      mark(`beat8-${k}-action`);
      const before = await sigs(page);
      await page.mouse.move(sb.x + sb.width / 2, sb.y + sb.height / 2, { steps: 14 }); await page.waitForTimeout(500);
      await page.mouse.click(sb.x + sb.width / 2, sb.y + sb.height / 2);
      await afterAction(`scroll${k}`, before);
      await shot(`beat8-${k}`);
      mark(`beat8-${k}-loaded`); await hold(page, 3000); mark(`beat8-${k}-end`);
    }

    // BEAT 9: Home, then Release all, hold 3 s
    const hb2 = await page.locator('button').filter({ hasText: /^Home$/ }).last().boundingBox();
    mark('beat9-action');
    await page.mouse.move(hb2.x + hb2.width / 2, hb2.y + hb2.height / 2, { steps: 14 }); await page.waitForTimeout(400);
    await page.mouse.click(hb2.x + hb2.width / 2, hb2.y + hb2.height / 2); await page.waitForTimeout(SETTLE_MS);
    const rb = await page.getByRole('button', { name: 'Release all' }).boundingBox();
    await page.mouse.move(rb.x + rb.width / 2, rb.y + rb.height / 2, { steps: 14 }); await page.waitForTimeout(400);
    await page.mouse.click(rb.x + rb.width / 2, rb.y + rb.height / 2);
    await page.waitForTimeout(2500);
    mark('beat9-loaded'); await hold(page, 3000); mark('beat9-end');
    log(`done; key delays ${JSON.stringify(keyDelays)}`);
  } finally {
    // control is released by the Release all click; if the walk threw, release it here when still visible
    const rel = page.getByRole('button', { name: 'Release all' }).first();
    if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); log('released control in finally'); }
    await shot('final');
    if (stop) await stop().catch(e => log(`recorder stop failed: ${e.message}`));
    await ctx.close(); await browser.close();
    if (!PREFLIGHT) fs.writeFileSync(path.join(OUT, 'group.marks.json'), JSON.stringify({ marks }, null, 1));
  }
})().catch(e => {
  console.log('FATAL', redact(String(e.message || e)).slice(0, 300));
  process.exit(1);
});
