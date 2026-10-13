// Video 22 ("What's new in VirtualPyTest"): the UI glow-up, the app in EN/FR/DE, a run report in FR/DE, and a
// report shared as an expiring snapshot link that is then revoked. Main site (Awesomation), a passed goto run on
// host-clone-1 (youtube-web search_results, RID). Creates one share link and revokes it on camera.
// Host IPs and the per-host version stamps on the Dashboard are blanked as they render; failed rows are hidden.
// Usage: PROMO_BASE=https://virtualpytest.angelstreet.io node whatsnew_capture.js [scout] -> raw22/whatsnew.mp4 + marks
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw22'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const RID = process.env.RID || 'aaa82683-8bbf-4ed7-b636-3443233ad435';
const TOUR = ['/run/tests', '/test-plan/coverage', '/builder/virtual-scripts', '/test-results/reports'];
const center = async l => { const b = await l.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; };
const click = async (page, l, pause = 600) => { await l.waitFor({ timeout: 30000 }); await l.scrollIntoViewIfNeeded(); await glide(page, ...(await center(l)), pause); };

// blank infra details and failed runs as they render (never on camera, even for a frame)
const SCRUB = () => {
  const ip = /\b(https?:\/\/)?\d{1,3}(\.\d{1,3}){3}(:\d+)?\b/g, stamp = /^\s*main-\d{4}\.\d\d\.\d\d-\d+\s*$/;
  const run = () => {
    const w = document.createTreeWalker(document.body || document, NodeFilter.SHOW_TEXT); let n;
    while ((n = w.nextNode())) {
      if (ip.test(n.nodeValue)) { ip.lastIndex = 0; n.nodeValue = n.nodeValue.replace(ip, ''); }
      if (stamp.test(n.nodeValue) && n.parentElement && !n.parentElement.closest('footer')) { const e = n.parentElement, g = e.parentElement; ((g && (g.textContent || '').trim().length < 40) ? g : e).style.visibility = 'hidden'; }
    }
    for (const tr of document.querySelectorAll('tbody tr')) if (/pokemon|labox/i.test(tr.textContent || '') && tr.style.display !== 'none') tr.style.display = 'none';
  };
  new MutationObserver(run).observe(document, { childList: true, subtree: true, characterData: true });
  document.addEventListener('DOMContentLoaded', run);
};

async function walk(page, ctx, mark, shot, log, startRec) {
  await page.goto(url('/'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(6000);
  await startRec(); mark('dashboard'); await shot('dashboard');
  // 1. the glow-up: a few restyled pages
  for (const p of TOUR) {
    await page.goto(url(p), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(900, 420, { steps: 12 }); await page.waitForTimeout(3500);
    const n = p.split('/').pop(); mark(`tour-${n}`); await shot(`tour-${n}`);
  }
  // 2. Settings: dark theme, then French, then German
  await page.goto(url('/'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(4000); mark('dash-again');
  const settings = page.getByRole('button', { name: /^settings$/i }).first();
  await click(page, settings, 700); await page.waitForTimeout(900); mark('menu'); await shot('menu');
  const menu = page.locator('[role="menu"], .MuiPopover-paper').last();
  const dark = menu.locator('button[aria-label*="ark" i], button[title*="ark" i]').first();
  if (await dark.count()) { await click(page, dark, 500); await page.waitForTimeout(1500); mark('dark'); } else log('no dark button found');
  const fr = page.getByRole('button', { name: /^(FR|Français)$/ }).first();
  await click(page, fr, 500); await page.waitForTimeout(1200);
  if (!/Tableau de bord/.test(await page.locator('body').innerText())) { await page.mouse.click(...(await center(fr))); await page.waitForTimeout(1200); }   // the first click can only close the theme tooltip
  if (!/Tableau de bord/.test(await page.locator('body').innerText())) throw new Error('app did not switch to French');
  await page.waitForTimeout(900); mark('fr'); await shot('fr');
  await click(page, page.getByRole('button', { name: /^(DE|Deutsch)$/ }).first(), 500); await page.waitForTimeout(1800); mark('de'); await shot('de');
  await click(page, page.getByRole('button', { name: /^(EN|English)$/ }).first(), 400);
  const light = page.locator('button[aria-label*="ight" i], button[title*="ight" i]').first(); if (await light.count()) await click(page, light, 400);
  await page.keyboard.press('Escape'); await page.waitForTimeout(800); mark('back-en');
  // 3. the run report, in French then German
  await page.goto(url('/test-results/reports'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(5000);
  const row = page.locator('tbody tr').filter({ hasText: /host - host-clone-1/ }).filter({ hasText: /goto/ }).first();
  const open = row.getByRole('button', { name: 'Open Report' }).first();
  const [pop] = await Promise.all([ctx.waitForEvent('page', { timeout: 20000 }), click(page, open, 600)]);   // glide clicks
  await pop.waitForLoadState('load'); const ru = pop.url(); await pop.close();
  await page.goto(ru, { waitUntil: 'load', timeout: 60000 }); await page.mouse.move(900, 400, { steps: 10 }); await page.waitForTimeout(3000); mark('report'); await shot('report');
  await click(page, page.getByRole('button', { name: /^(FR|Français)$/ }).first(), 600); await page.waitForTimeout(2500); mark('report-fr'); await shot('report-fr');
  await click(page, page.getByRole('button', { name: /^(DE|Deutsch)$/ }).first(), 500); await page.waitForTimeout(2500); mark('report-de'); await shot('report-de');
  await click(page, page.getByRole('button', { name: /^(EN|English)$/ }).first(), 500); await page.waitForTimeout(1200);
  // 4. share it: the report's share icon opens the app's Share dialog
  const shareIcon = page.locator('button[title*="hare" i], a[title*="hare" i], [aria-label*="hare" i]').first();
  const href = await shareIcon.getAttribute('href').catch(() => null);
  const [sp] = await Promise.all([ctx.waitForEvent('page', { timeout: 6000 }).catch(() => null), click(page, shareIcon, 600)]); mark('share-click');
  let target = sp ? sp.url() : (href ? new URL(href, page.url()).href : null); if (sp) await sp.close();
  if (!target && /share=/.test(page.url())) target = page.url();
  if (!target) target = url(`/test-results/reports?share=${RID}`);
  if (page.url() !== target) await page.goto(target, { waitUntil: 'load', timeout: 120000 });
  const dlg = page.locator('[role="dialog"]').first(); await dlg.waitFor({ timeout: 30000 }); await page.waitForTimeout(2500); mark('dialog'); await shot('dialog');
  await click(page, dlg.getByRole('button', { name: /create link/i }), 800); await page.waitForTimeout(3500); mark('created'); await shot('created');
  let link = null;   // the dialog shows the share link and a delete link: take the share one
  for (const inp of await dlg.locator('input').all()) { const v = await inp.inputValue().catch(() => ''); if (/\/share\//.test(v) && !/\/delete\//.test(v) && !link) link = v; }
  if (!link) throw new Error('no share link in the dialog');
  log('share link created (key not printed)');
  // 5. the snapshot, as anyone with the link sees it (public route, no account)
  await page.goto(link, { waitUntil: 'load', timeout: 60000 }); await page.mouse.move(900, 450, { steps: 12 }); await page.waitForTimeout(5000); mark('snapshot'); await shot('snapshot');
  await page.mouse.wheel(0, 500); await page.waitForTimeout(2500); mark('snapshot-scrolled');
  // 6. Shared links tab: revoke it
  await page.goto(url('/test-results/reports'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(4000);
  await click(page, page.getByRole('button', { name: /^shared links$/i }).first(), 700); await page.waitForTimeout(3000); mark('links'); await shot('links');
  await click(page, page.getByRole('button', { name: /^all$/i }).first(), 400); await page.waitForTimeout(1200);
  await click(page, page.getByPlaceholder(/filter by report/i).first(), 300); await page.keyboard.type('goto', { delay: 70 }); await page.waitForTimeout(1500);
  const revoke = page.getByRole('button', { name: /^revoke$/i }).first();
  await click(page, revoke, 700); await page.waitForTimeout(1200); mark('confirm'); await shot('confirm');
  const confirm = page.getByRole('button', { name: /^confirm revoke$/i }).first();
  await click(page, confirm, 600);
  await page.waitForTimeout(3000); mark('revoked'); await shot('revoked');
  await page.waitForTimeout(1500); mark('end');
  return link;
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); await ctx.addInitScript(SCRUB);
  const page = await ctx.newPage();
  let stop = null; const marks = []; let t0 = Date.now();
  const startRec = async () => { if (!scout) stop = await startRecorder(page, 'whatsnew'); t0 = Date.now(); };
  const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); };
  const log = s => console.log(redact(s));
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-${name}.png`) });
  try { await walk(page, ctx, mark, shot, log, startRec); } catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  if (!scout) fs.writeFileSync(path.join(OUT, 'whatsnew.marks.json'), JSON.stringify({ marks }, null, 1));
  if (stop) await stop();
  await ctx.close(); await browser.close();
  console.log(marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
