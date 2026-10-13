// Video 11 (CI/CD: from commit to report): the main server (Awesomation), host-clone-1 device `host`, interface youtube-web.
// Beat 1: Build Campaign page (/run/build) - name "Smoke: youtube-web", click three scripts (goto, superping, dns lookup), Save.
// Beat 2: the pipeline call - a REAL curl from this machine (POST /server/campaigns/execute, X-API-Key) fired while the
//         Monitor Tests > Campaigns tab is open; its output is saved to raw11/curl.txt with the key shown as $VPT_API_KEY.
// Beat 3: the run appearing and progressing in Monitor Tests > Campaigns, then its campaign report.
// Lease node1-vpt host-clone-1 first (deploy skill). The CI/CD Reports page is NOT filmed (runs partial/failed).
// Usage: node cicd_capture.js scout   -> raw11/scout-*.png + scout.log (no recording)
//        node cicd_capture.js         -> raw11/cicd.mp4 + cicd.marks.json + take-*.png + take.log + curl.txt
// The builder's parameter panel never loads ("Loading parameters..." - the page calls GET /server/script/analyze/<name>,
// which does not exist), so goto's parameters (youtube-web, node home) are added through updateCampaign right after Save.
process.env.PROMO_BASE = process.env.PROMO_BASE || 'https://virtualpytest.angelstreet.io';
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path'); const { spawn } = require('child_process');
const OUT = path.join(__dirname, 'raw11'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, SERVER, TEAM, url, CURSOR, redact, api, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const NAME = 'Smoke: youtube-web'; const HOST = 'host-clone-1', DEVICE = 'host';
const SCRIPTS = [['goto', 'Goto', 'goto'], ['gw/superping', 'superping', 'superping'], ['gw/dns_lookuptime', 'dns lookup', 'dns']];   // [script, row text, search]

async function clickBox(page, loc, pause = 600) { await loc.waitFor({ timeout: 30000 }); await loc.scrollIntoViewIfNeeded(); const b = await loc.boundingBox(); await glide(page, b.x + b.width / 2, b.y + b.height / 2, pause); }
const vis = (page, text, opts = {}) => page.getByText(text, { exact: true, ...opts }).locator('visible=true').first();

async function deleteOld() {
  const l = await api('GET', '/server/campaigns/getAllCampaigns');
  for (const c of (l.campaigns || [])) if (c.campaign_name === NAME) console.log('deleted old', c.campaign_id, (await api('DELETE', `/server/campaigns/deleteCampaign/${c.campaign_id}`)).success);
}

async function walk(page, mark, shot, log, scout, ctx) {
  await deleteOld();
  await page.goto(url('/run/build'), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(7000);
  // the Existing Campaigns list holds other teams' demo names: keep it off camera
  await page.evaluate(() => { for (const h of document.querySelectorAll('h6, .MuiTypography-root')) if (h.textContent.trim() === 'Existing Campaigns') { let e = h; while (e.parentElement && !e.classList.contains('MuiPaper-root')) e = e.parentElement; e.style.display = 'none'; } });
  mark('build'); await shot('build');
  const nameField = page.getByLabel('Campaign Name').locator('visible=true'); await clickBox(page, nameField, 400); await page.keyboard.type(NAME, { delay: 45 });
  await clickBox(page, page.getByLabel('Description').locator('visible=true'), 300); await page.keyboard.type('Pipeline smoke: UI navigation and network checks on host-clone-1', { delay: 25 });
  mark('named'); await shot('named');
  for (const [, label, term] of SCRIPTS) {
    const sb = page.getByPlaceholder('Search by name...').locator('visible=true').first();
    await clickBox(page, sb, 300); await page.keyboard.press('Control+A'); await page.keyboard.type(term, { delay: 60 }); await page.waitForTimeout(1200);
    await clickBox(page, vis(page, label), 700);   // first match = the script row (S badge) await page.waitForTimeout(900);
  }
  mark('scripts'); await shot('scripts');
  await page.evaluate(() => window.scrollTo(0, 0));
  const save = page.getByRole('button', { name: /^save$/i }).locator('visible=true').first();
  await clickBox(page, save, 900); await page.waitForTimeout(3500); mark('saved'); await shot('saved');
  // find the campaign, add goto's parameters (off camera)
  let camp = null;
  for (let i = 0; i < 10 && !camp; i++) { const l = await api('GET', '/server/campaigns/getAllCampaigns'); camp = (l.campaigns || []).find(c => c.campaign_name === NAME); if (!camp) await page.waitForTimeout(1500); }
  if (!camp) throw new Error('campaign not saved');
  const full = (await api('GET', `/server/campaigns/getCampaign/${camp.campaign_id}`)).campaign;
  const configs = (full.script_configurations || []).map(s => /^goto/.test(s.script_name) ? { ...s, parameters: { userinterface: 'youtube-web', node: 'home' } } : s);
  const up = await api('PUT', `/server/campaigns/updateCampaign/${camp.campaign_id}`, { script_configurations: configs, userinterface_name: 'youtube-web' });
  log(`campaign ${camp.campaign_id} scripts=${configs.map(s => s.script_name).join(',')} params updated=${up.success}`);
  // Monitor Tests > Campaigns tab, then fire the curl
  await page.goto(url('/run/monitor?tab=campaigns'), { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(800, 450); await page.waitForTimeout(6000);
  const tab = page.getByRole('button', { name: /^campaigns$/i }).locator('visible=true').first(); if (await tab.isVisible().catch(() => false)) await clickBox(page, tab, 600);
  // filter to our campaign (other teams' campaigns stay off camera), collapse Scheduled, open Running
  await clickBox(page, page.getByPlaceholder('Search...').locator('visible=true').first(), 400); await page.keyboard.type('youtube-web', { delay: 80 }); await page.waitForTimeout(1500);
  const sched = page.getByText(/^Campaigns Scheduled/).locator('visible=true').first(); if (await sched.isVisible().catch(() => false)) { await clickBox(page, sched, 400); await page.waitForTimeout(800); }
  await clickBox(page, page.getByText(/^Campaigns Running/).locator('visible=true').first(), 600); await page.waitForTimeout(1200);
  mark('monitor'); await shot('monitor');
  const body = { campaign_id: camp.campaign_id, name: NAME, host_name: HOST, device_id: DEVICE, script_configurations: configs.map(s => ({ script_name: s.script_name, parameters: s.parameters || {} })) };
  const shown = `curl -X POST "${SERVER}/server/campaigns/execute?team_id=<team_id>" \\\n  -H "X-API-Key: $VPT_API_KEY" -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(body, null, 2)}'`;
  const resp = await new Promise((resolve) => {
    const p = spawn('curl', ['-sS', '-X', 'POST', `${SERVER}/server/campaigns/execute?team_id=${TEAM}`, '-H', `X-API-Key: ${process.env.API_KEY}`, '-H', 'Content-Type: application/json', '-d', JSON.stringify(body)]);
    let o = ''; p.stdout.on('data', d => o += d); p.stderr.on('data', d => o += d); p.on('close', () => resolve(o));
  });
  mark('curl');
  let pretty = resp; try { const j = JSON.parse(resp); if (j.lock_info) j.lock_info = '...'; pretty = JSON.stringify(j, null, 2); } catch (e) {}   // lock_info elided for the card
  fs.writeFileSync(path.join(OUT, scout ? 'scout-curl.txt' : 'curl.txt'), `$ ${shown}\n\n${redact(pretty).replaceAll(process.env.API_KEY || '\u0000', '$VPT_API_KEY')}\n`);
  log('curl response: ' + redact(resp).slice(0, 400));
  // the run appears and progresses; poll the page until it is done
  let last = '';
  for (let i = 0; i < 120; i++) {
    await page.waitForTimeout(3000);
    const txt = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ');
    const m = txt.slice(txt.indexOf('Monitor Tests'), txt.indexOf('Monitor Tests') + 600);
    if (m !== last) { log(`t+${(i + 1) * 3}s ${m.slice(0, 450)}`); last = m; }
    if (i % 4 === 3) await shot(`run-${String(i + 1).padStart(3, '0')}`);
    if (i === 2) mark('run-visible');
    if (/Campaigns Running - 0/.test(txt) && i > 5) break;
  }
  mark('done'); await shot('done');
  await clickBox(page, page.getByText(/^Last Campaign Executions/).locator('visible=true').first(), 600); await page.waitForTimeout(2500); mark('history'); await shot('history');
  // expand the newest run (per-test results), then open its campaign report
  const row = page.locator('tr').filter({ hasText: NAME }).locator('visible=true').first();
  await clickBox(page, row.locator('svg').first(), 700); await page.waitForTimeout(2500); mark('expanded'); await shot('expanded');
  const link = row.locator('td').nth(5).locator('svg, button, a').first();
  const [popup] = await Promise.all([ctx.waitForEvent('page', { timeout: 15000 }).catch(() => null), clickBox(page, link, 800)]);
  if (popup) { await popup.waitForLoadState('load').catch(() => {}); const ru = popup.url(); await popup.close(); log('report url: ' + redact(ru).replace(/\?.*/, ''));
    await page.goto(ru, { waitUntil: 'load', timeout: 60000 }); await page.mouse.move(900, 500); await page.waitForTimeout(4000); mark('report'); await shot('report'); await page.waitForTimeout(5000); }
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR);
  // other teams' demo rows (names with the customer prefix) must never reach the screen, even for a second: hide them as they render
  await ctx.addInitScript(() => { const hide = () => { for (const tr of document.querySelectorAll('tr, [role="row"]')) if (/labox/i.test(tr.textContent || '') && tr.style.display !== 'none') tr.style.display = 'none'; }; new MutationObserver(hide).observe(document, { childList: true, subtree: true, characterData: true }); });
  const page = await ctx.newPage();
  const stop = scout ? null : await startRecorder(page, 'cicd');
  const marks = []; const t0 = Date.now(); const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); console.log('mark', l, ((Date.now() - t0) / 1000).toFixed(1)); };
  const logf = path.join(OUT, scout ? 'scout.log' : 'take.log'); fs.writeFileSync(logf, '');
  const log = s => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(s)}`; fs.appendFileSync(logf, l + '\n'); console.log(l); };
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-${name}.png`) });
  try { await walk(page, mark, shot, log, scout, ctx); }
  catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  if (stop) await stop();
  await ctx.close(); await browser.close();
  if (!scout) fs.writeFileSync(path.join(OUT, 'cicd.marks.json'), JSON.stringify({ marks }, null, 1));
})();
