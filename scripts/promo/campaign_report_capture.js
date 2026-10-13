// Video 11 closing beat: the campaign report, each script row expanded, then one script's report and its log.
// Read-only (a static report page, no device). Usage: node campaign_report_capture.js [scout] -> raw11/creport.mp4 + marks
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw11'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, url, CURSOR, redact, scrubSecrets, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const REPORT = process.env.REPORT || 'https://virtualpytest.angelstreet.io/virtualpytest/script-reports/host_vnc/campaign_orchestrator_c3bec53f-785f-48d4-a568-07dc1273001b_53e7d748-1a45-40f4-8e2b-86635cff94bb/report.html';
const center = async l => { const b = await l.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; };

async function walk(page, ctx, mark, shot, log, startRec) {
  // the report needs a signed URL, which the app makes when its Report link is clicked: open it from Monitor Tests
  await page.goto(url('/run/monitor?tab=campaigns'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(6000);
  const tab = page.getByRole('button', { name: /^campaigns$/i }).locator('visible=true').first(); if (await tab.isVisible().catch(() => false)) await tab.click();
  await page.getByPlaceholder('Search...').locator('visible=true').first().fill('youtube-web'); await page.waitForTimeout(1500);
  const link = page.getByRole('button', { name: 'Open report' }).locator('visible=true').first();
  if (!(await link.waitFor({ timeout: 4000 }).then(() => true).catch(() => false))) {   // the history section may start closed
    await page.getByText(/^Last Campaign Executions/).locator('visible=true').first().click(); await page.waitForTimeout(3000);
  }
  await link.scrollIntoViewIfNeeded();
  const [popup] = await Promise.all([ctx.waitForEvent('page', { timeout: 15000 }).catch(() => null), link.click()]);
  if (!popup) throw new Error('no report popup');
  await popup.waitForLoadState('load').catch(() => {}); const ru = popup.url(); await popup.close();
  await page.goto(ru, { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(3000); await scrubSecrets(page);
  await startRec(); mark('report'); await shot('report'); await page.mouse.move(900, 450, { steps: 10 }); await page.waitForTimeout(2500);
  // expand the three script rows ("details" toggles)
  const toggles = page.locator('text=/details/i');
  const n = Math.min(await toggles.count(), 3); log(`detail toggles: ${await toggles.count()}`);
  for (let i = 0; i < n; i++) { await glide(page, ...(await center(toggles.nth(i))), 500); await page.waitForTimeout(1200); }
  await page.mouse.move(900, 300, { steps: 15 }); await page.waitForTimeout(2500); mark('expanded'); await shot('expanded');
  // one script's report (first row), then its logs; links may open a new tab: follow it in this page
  const open = async (name, label) => {
    const link = page.getByRole('link', { name: new RegExp(`^${name}$`, 'i') }).first();
    const href = await link.getAttribute('href').catch(() => null);
    await glide(page, ...(await center(link)), 600);
    const target = href && new URL(href, page.url()).href;
    if (target && page.url() !== target) await page.goto(target, { waitUntil: 'load', timeout: 60000 });
    await scrubSecrets(page);   // never film credentials or IPs that a report/log prints
    await page.mouse.move(900, 450, { steps: 15 }); await page.waitForTimeout(5000); mark(label); await shot(label);
  };
  await open('Report', 'script-report');
  await page.goBack({ waitUntil: 'load' }).catch(() => {}); await page.waitForTimeout(2000);
  await open('Logs', 'script-logs');
  await page.waitForTimeout(1500); mark('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR);
  await ctx.addInitScript(() => { const hide = () => { for (const tr of document.querySelectorAll('tr, [role="row"]')) if (/labox/i.test(tr.textContent || '') && tr.style.display !== 'none') tr.style.display = 'none'; }; new MutationObserver(hide).observe(document, { childList: true, subtree: true, characterData: true }); });
  const page = await ctx.newPage();
  let stop = null; const marks = []; let t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  const startRec = async () => { if (!scout) stop = await startRecorder(page, 'creport'); t0 = Date.now(); ctx.on('page', p => p.close().catch(() => {})); };
  const log = s => console.log(redact(s));
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-cr-${name}.png`) });
  try { await walk(page, ctx, mark, shot, log, startRec); } catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'creport.marks.json'), JSON.stringify({ marks }, null, 1));
  console.log(marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
