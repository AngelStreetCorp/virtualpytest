// Video 23 (the fingerprint): main server (Awesomation), host-clone-1 / host (a browser), interface sauce-demo.
// Navigation Editor: Take Control, Localize on home, Go To cart + Localize, the node's fingerprint, an off-map page
// (opened OFF CAMERA by the normal action route) + Localize, Go To home. Real clicks only.
// Lease host-clone-1/host first (deploy skill) and release it after. The device is put on home before the take.
// Usage: PROMO_BASE=https://virtualpytest.angelstreet.io node localize_capture.js [scout]
//        scout -> raw23/scout-*.png + scout.log, no recording; otherwise raw23/localize.mp4 + localize.marks.json + take-*.png
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw23'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, api, relay, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const UI = 'sauce-demo'; const HOST = 'host-clone-1'; const DEV = 'host';
const OFFMAP = process.env.OFFMAP_URL || 'https://example.com';
const center = async l => { await l.waitFor({ timeout: 30000 }); const b = await l.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; };
const sleep = ms => new Promise(r => setTimeout(r, ms));

// the tree id of the interface (API, off camera)
async function treeId() {
  const t = await api('GET', '/server/navigationTrees'); const uis = await api('GET', '/server/userinterface/getAllUserInterfaces');
  const ui = (Array.isArray(uis) ? uis : uis.userinterfaces || []).find(u => u.name === UI);
  return (t.trees || []).find(x => x.userinterface_id === ui.id && x.is_root_tree).id;
}
// move the device with the normal navigation route and wait for it to finish (off camera)
async function gotoApi(tree, label, log) {
  const r = await api('POST', `/server/navigation/execute/${tree}`, { target_node_label: label, host_name: HOST, device_id: DEV, userinterface_name: UI });
  for (let i = 0; i < 40; i++) { await sleep(2500); const s = await api('GET', `/server/navigation/execution/${r.execution_id}/status?host_name=${HOST}&device_id=${DEV}`).catch(() => ({}));
    if (s.progress >= 100 || s.error) { log(`api goto ${label}: ${s.error || s.message}`); return; } }
  log(`api goto ${label}: no final status`);
}

async function walk(page, ctx, mark, shot, log, startRec, scout) {
  const tree = await treeId(); log('tree ' + tree.slice(0, 8));
  await gotoApi(tree, 'products', log); await gotoApi(tree, 'home', log); await sleep(4000);   // two hops: the tracked position can disagree with the real page
  await page.goto(url(`/navigation-editor/${UI}`), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450);
  await page.getByText(/^register$/i).first().waitFor({ timeout: 60000 }); await page.waitForTimeout(6000);
  const layout = page.locator('button[title="Auto Layout"]').first();
  if (await layout.isVisible().catch(() => false)) { await glide(page, ...(await center(layout)), 500); await page.waitForTimeout(2500); }
  const fit = page.locator('button[title="fit view"]').first();
  if (await fit.isVisible().catch(() => false)) { await glide(page, ...(await center(fit)), 500); await page.waitForTimeout(1500); }
  // keep the map clear of the stream panels (bottom): one zoom-out step, then pan the canvas up (off camera)
  const zout = page.locator('.react-flow__controls-zoomout').first();
  if (await zout.isVisible().catch(() => false)) { for (let i = 0; i < 2; i++) { await zout.click(); await page.waitForTimeout(700); } }
  await page.mouse.move(800, 300); await page.mouse.down(); await page.mouse.move(800, 200, { steps: 10 }); await page.mouse.up(); await page.waitForTimeout(800);
  await shot('1-editor'); await startRec(); mark('editor'); await page.waitForTimeout(2500);

  // 1. Target + Take Control
  const sel = page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first();
  await glide(page, ...(await center(sel)), 700); await page.waitForTimeout(700);
  await glide(page, ...(await center(page.locator('[role="option"]').filter({ hasText: new RegExp(HOST) }).first())), 700); await page.waitForTimeout(1200);
  await glide(page, ...(await center(page.getByRole('button', { name: /^control$/i }).first())), 600); mark('control');
  await page.waitForTimeout(12000); await shot('2-control');
  // clear the clutter and enlarge the device stream: collapse the two other panels, expand the VNC one
  const btnAt = async (testid, which) => { const all = await page.evaluate(id => [...document.querySelectorAll(`svg[data-testid="${id}"]`)].map(e => { const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; }).filter(p => p.y > 500 && p.y < 880), testid);
    all.sort((a, b) => a.x - b.x); return which === 'first' ? all[0] : all[all.length - 1]; };
  for (let i = 0; i < 2; i++) { const c = await btnAt('KeyboardArrowDownIcon', 'last'); if (c && c.x > 700) { await glide(page, c.x, c.y, 500); await page.waitForTimeout(900); } }
  const big = await btnAt('OpenInFullIcon', 'first');
  if (big && big.x < 600) { await glide(page, big.x, big.y, 600); await page.waitForTimeout(9000); log('stream enlarged'); }
  await shot('3-stream');

  const localize = async (name) => {
    const btn = page.locator('[aria-label="Localize current screen"]').first();
    await glide(page, ...(await center(btn)), 600);
    await page.locator('.MuiPopover-paper').getByText(/Excluded \d+ of \d+/).waitFor({ timeout: 40000 });
    const txt = (await page.locator('.MuiPopover-paper').innerText()).replace(/\s*\n+\s*/g, ' | '); log(`popover ${name}: ${txt}`); return txt;
  };
  const closePopover = async () => { await page.keyboard.press('Escape'); await page.waitForTimeout(600); };

  // 2. Localize on home
  let txt = await localize('1'); mark('localize-1'); await shot('localize-1'); await page.waitForTimeout(3000); await closePopover();
  if (!/Localized: home/.test(txt)) log('WARN localize-1 is not home');

  // 3. cart: select the node, Go To, Run
  const node = async name => page.locator('.react-flow__node').filter({ has: page.getByText(new RegExp(`^${name}$`)) }).first();
  await glide(page, ...(await center(await node('cart'))), 700); await page.waitForTimeout(800); await shot('4-cart-selected');
  await glide(page, ...(await center(page.getByRole('button', { name: /^go to$/i }).first())), 600); await page.waitForTimeout(1500); await shot('5-goto-panel');
  await glide(page, ...(await center(page.getByRole('button', { name: /^run/i }).first())), 600); mark('goto');
  await page.waitForTimeout(9000);
  const xg = page.locator('.MuiPaper-root:has-text("Go To Node") [data-testid="CloseIcon"]').first();
  if (await xg.isVisible().catch(() => false)) await glide(page, ...(await center(xg)), 500);
  await page.waitForTimeout(3000); mark('moved'); await shot('6-moved');
  txt = await localize('2'); mark('localize-2'); await shot('localize-2'); await page.waitForTimeout(3000);
  if (!/Localized: cart/.test(txt)) log('WARN localize-2 is not cart');
  await closePopover();

  // 4. the node's edit dialog: screenshot + fingerprint pill
  await glide(page, ...(await center(await node('cart'))), 600); await page.waitForTimeout(800);
  await glide(page, ...(await center(page.getByRole('button', { name: /^edit$/i }).first())), 600); await page.waitForTimeout(3000);
  await shot('7-edit'); mark('fingerprint'); await page.waitForTimeout(3500);
  const closeBtn = page.locator('.MuiDialog-root').getByRole('button', { name: /^(cancel|close)$/i }).first();
  if (await closeBtn.isVisible().catch(() => false)) await glide(page, ...(await center(closeBtn)), 500); else await page.keyboard.press('Escape');
  await page.waitForTimeout(1200);

  // 5. off-map: OFF CAMERA open a page that is not on the map (normal action route), then Localize on camera
  mark('cut-start');
  const act = await api('POST', '/server/action/executeBatch', { host_name: HOST, device_id: DEV, userinterface_name: UI,
    actions: [{ command: 'navigate_to_url', params: { url: OFFMAP, wait_time: 3000 } }] });
  log('offmap action: ' + JSON.stringify(act).slice(0, 160)); await page.waitForTimeout(12000); await shot('8-offmap-stream'); mark('cut-end');
  txt = await localize('3'); mark('offmap'); await shot('localize-offmap'); await page.waitForTimeout(3000);
  if (!/No confident match/.test(txt)) log('WARN offmap answer: ' + txt);
  await closePopover();
  // back to home
  await glide(page, ...(await center(await node('home'))), 600); await page.waitForTimeout(800);
  await glide(page, ...(await center(page.getByRole('button', { name: /^go to$/i }).first())), 600); await page.waitForTimeout(1200);
  await glide(page, ...(await center(page.getByRole('button', { name: /^run/i }).first())), 600);
  await page.waitForTimeout(9000);
  const xg2 = page.locator('.MuiPaper-root:has-text("Go To Node") [data-testid="CloseIcon"]').first();
  if (await xg2.isVisible().catch(() => false)) await glide(page, ...(await center(xg2)), 500);
  await page.waitForTimeout(3000); mark('back-home'); await shot('9-back-home');
  txt = await localize('4'); await page.waitForTimeout(2500); await closePopover();
  mark('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await relay(ctx); const page = await ctx.newPage();
  const marks = []; let t0 = Date.now(); const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  let stop = null; const startRec = async () => { if (scout) { t0 = Date.now(); marks.length = 0; return; } stop = await startRecorder(page, 'localize'); t0 = Date.now(); marks.length = 0; };
  const logf = path.join(OUT, `${scout ? 'scout' : 'take'}.log`); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-${name}.png`) });
  try { await walk(page, ctx, mark, shot, log, startRec, scout); }
  catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  // release control, or the device stays locked to this (closed) browser session
  const rel = page.getByRole('button', { name: /^release$/i }).first();
  if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); await page.waitForTimeout(2500); log('released control'); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'localize.marks.json'), JSON.stringify({ marks }, null, 1));
})();
