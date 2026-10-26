/**
 * drone_tile_probe.js — headless check that the Tello tile on the Device page
 * renders its Wi-Fi overlay instead of a black frame, and that the click is
 * gated until the drone is paired.
 *
 * Standalone runner (NOT a *.spec.js, so `playwright test` / CI never fires it
 * against the live site on its own). Run it explicitly:
 *
 *   E2E_BASE_URL=https://virtualpytest.angelstreet.io \
 *   E2E_AUTO_SIGN_TOKEN=<AUTO_SIGN_TOKEN from the server .env> \
 *   node tests/e2e/playwright/drone_tile_probe.js
 *
 * Optional:
 *   PROBE_SERVER=vpt-pi4     server picker entry that owns the drone
 *   PROBE_TARGET="Tello 1"   "All Targets" entry to narrow the grid to
 *   PROBE_SCHEME=dark|light  colour scheme for the capture (default: both)
 *   E2E_OUT_DIR=<dir>        where screenshots + payloads land (default /tmp/drone-probe)
 *
 * Exit code 0 = overlay present, 1 = the tile rendered but stayed black.
 *
 * Why the filter is needed: the pi server hosts 28 devices and the grid pages
 * at 24, so vpt-nipogi's HLS devices fill page 1 and the drone is on page 2.
 * "All Targets" -> the drone narrows the grid to exactly one tile, which is
 * also the smallest possible reproduction.
 */
const path = require('path');
const fs = require('fs');

/** Playwright is gitignored, so `npm ci` is required and a git worktree has
 *  no local copy. Try PW_NODE_MODULES, then this checkout, then the primary
 *  checkout next to it (worktrees live beside the primary, not inside it). */
function loadPlaywright() {
  const parent = path.dirname(path.dirname(path.dirname(__dirname)));
  const candidates = [
    process.env.PW_NODE_MODULES,
    path.join(__dirname, 'node_modules'),
    path.join(parent, 'virtualpytest/tests/e2e/playwright/node_modules'),
  ].filter(Boolean);
  for (const base of candidates) {
    try { return require(path.join(base, 'playwright')); } catch (e) { /* next */ }
  }
  throw new Error(
    `playwright not found. Tried:\n  ${candidates.join('\n  ')}\n` +
    'Run `npm ci` in tests/e2e/playwright, or set PW_NODE_MODULES.'
  );
}
const { chromium } = loadPlaywright();

const BASE = process.env.E2E_BASE_URL || 'https://virtualpytest.angelstreet.io';
const TOK = process.env.E2E_AUTO_SIGN_TOKEN;
const OUT = process.env.E2E_OUT_DIR || '/tmp/drone-probe';
const SERVER = process.env.PROBE_SERVER || 'vpt-pi4';
const TARGET = process.env.PROBE_TARGET || 'Tello 1';
const SCHEMES = process.env.PROBE_SCHEME ? [process.env.PROBE_SCHEME] : ['light', 'dark'];

if (!TOK) {
  console.error('E2E_AUTO_SIGN_TOKEN is required (AUTO_SIGN_TOKEN in the server .env)');
  process.exit(2);
}
fs.mkdirSync(OUT, { recursive: true });

/** Navigate, pick the server, narrow the grid to the drone. */
async function openDroneTile(page) {
  await page.goto(`${BASE}/device-control?auto_signed=${encodeURIComponent(TOK)}`, {
    waitUntil: 'domcontentloaded',
    timeout: 60000,
  });
  await page.waitForTimeout(9000); // server discovery round

  await page.locator('[role="combobox"]').first().click();
  await page.waitForTimeout(900);
  const servers = (await page.locator('[role="option"]').allInnerTexts()).map(s => s.replace(/\s+/g, ' ').trim());
  console.log('  servers:', servers.join(' | '));

  await page.locator('[role="option"]', { hasText: SERVER }).first().click();
  await page.waitForTimeout(10000); // switch + stream init

  // The filter is not optional (28 devices on the pi, grid pages at 24, so the
  // drone lands on page 2) and the dropdown silently no-ops on a slow render:
  // the probe then measures a grid of HLS tiles and reports a false failure.
  // Retry, and CONFIRM the filter landed instead of assuming the click worked.
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const targets = page.locator('[role="combobox"]', { hasText: 'All Targets' });
    if (await targets.count()) {
      await targets.first().click();
      await page.waitForTimeout(1400);
      await page
        .locator('[role="option"]', { hasText: TARGET })
        .first()
        .click({ timeout: 15000 })
        .catch(() => {});
      await page.waitForTimeout(2500);
    }
    const filtered = await page.evaluate(
      (t) => (document.body.innerText || '').includes(t),
      TARGET
    );
    if (filtered) break;
    console.log(`  (target filter did not land, retry ${attempt + 1})`);
    await page.keyboard.press('Escape').catch(() => {});
    await page.waitForTimeout(1500);
  }
  // Long enough for useDroneWifiStatus to finish its first poll (status -> scan).
  await page.waitForTimeout(14000);
}

/** What the tile is actually showing. */
async function readTile(page) {
  return page.evaluate(() => {
    const body = document.body.innerText || '';
    const h = Array.from(document.querySelectorAll('h6')).map(x => x.innerText.trim());
    // Key on the placeholder image, not on wording: the copy is deliberately
    // terse ("AP unavailable") and changed while the probe was written, so a
    // text match would report a false failure the moment the words changed.
    const ph = document.querySelector('img[src*="tello_placeholder"]');
    return {
      build: (body.match(/main-[\d.]+-[\d]+/) || [])[0] || null,
      deviceCount: (body.match(/Device\s+(\d+)/) || [])[1] || null,
      headings: h,
      hasPlaceholder: Boolean(ph),
      // /Scan/ not /Scan again/: the chip is labelled "Scan" and only reads
      // "Scanning…" while a rescan is in flight, so the old alternation would
      // report false on an idle tile.
      hasScanChip: /Scan/.test(body),
      // Short copy: headline plus, when present, the "what do I do" line.
      overlay: (body.match(/Checking…|AP unavailable|Connecting…|AP check failed|Power on the drone|cannot be reached/g) || []).slice(0, 4),
      // A tile that fell back to the generic player's failure text.
      leak: /not found on the server|stream restart required/i.test(body),
    };
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  let failed = false;

  for (const scheme of SCHEMES) {
    // ignoreHTTPSErrors: the pi server is reachable over an IP whose certificate
    // is not browser-trusted, so a strict context refuses every request.
    const ctx = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1500, height: 1000 },
      colorScheme: scheme,
    });
    const page = await ctx.newPage();

    const droneCalls = [];
    page.on('response', r => { if (/\/server\/drone\//.test(r.url())) droneCalls.push(`${r.status()} ${r.url()}`); });

    console.log(`\n[${scheme}] ${BASE}/device-control`);
    await openDroneTile(page);

    const tile = await readTile(page);
    console.log('  build      :', tile.build);
    console.log('  devices    :', tile.deviceCount);
    console.log('  headings   :', tile.headings.join(', ') || '(none)');
    console.log('  overlay    :', tile.overlay.join(' / ') || '(NONE — this is the bug)');
    console.log('  placeholder:', tile.hasPlaceholder);
    console.log('  scan chip  :', tile.hasScanChip);
    console.log('  raw leak   :', tile.leak);
    if (droneCalls.length) console.log('  drone api  :', droneCalls.slice(0, 3).join(' | '));

    await page.screenshot({ path: `${OUT}/drone-grid-${scheme}.png` });
    // data-device-tile is on the WRAPPER Box, which is height:100% of a grid
    // item that can be far taller than the 180px card inside it (the 9:16
    // stretch layout). Screenshotting the wrapper yields a tall crop of a
    // short tile and reads like a broken layout. Take the Card that
    // RecHostPreview actually renders.
    const tileEl = page.locator('[data-device-tile] .MuiCard-root').first();
    if (await tileEl.count()) await tileEl.screenshot({ path: `${OUT}/drone-tile-${scheme}.png` });

    if (!tile.hasPlaceholder) {
      console.log(`  FAIL [${scheme}]: tile rendered with no drone placeholder`);
      failed = true;
    } else if (tile.leak) {
      console.log(`  FAIL [${scheme}]: raw server/player error text is leaking into the tile`);
      failed = true;
    } else {
      console.log(`  PASS [${scheme}]: drone placeholder is on screen`);
    }
    await ctx.close();
  }

  await browser.close();
  console.log(`\nartifacts -> ${OUT}`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error('FAILED', e); process.exit(1); });