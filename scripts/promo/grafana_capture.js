// Video 20: Atlas builds a Grafana dashboard. Main server (Awesomation), Atlas chat (/ai-agent), Target host-clone-1,
// prompt: a canvas "for my selected devices" (scope = host-clone-1 only, so no fleet-wide labox rows); its
// "Open in Grafana" link opens the draft dashboard, followed in this page. Grafana needs its own login: done off
// camera first with GRAFANA_ADMIN_* from ~/virtualpytest/.env (never printed). Read-only, no device driven.
// Usage: PROMO_BASE=https://virtualpytest.angelstreet.io node grafana_capture.js [scout] -> raw20/grafana.mp4 + marks
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const OUT = path.join(__dirname, 'raw20'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, BASE, url, CURSOR, redact, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const PROMPT = process.env.PROMPT || 'Build a canvas for my selected devices: pass rate by device, duration trend and incidents over the last 7 days';   // scoped to the header Target (BUG-0405)
const TARGET = /host-clone-1/;
const FOOTER = /\b\d+\.\ds\b/g;   // one per completed agent turn
const center = async l => { const b = await l.boundingBox(); return [b.x + b.width / 2, b.y + b.height / 2]; };

function envVal(name) {
  const line = fs.readFileSync(path.join(__dirname, '../../.env'), 'utf8').split('\n').find(l => l.startsWith(name + '='));
  return line ? line.slice(name.length + 1).trim().replace(/^["']|["']$/g, '') : '';
}

async function grafanaLogin(page, log) {
  await page.goto(`${BASE}/grafana/login`, { waitUntil: 'load', timeout: 60000 });
  const user = page.locator('input[name="user"]');
  // the login page is a SPA: wait for its form (or the redirect away from /login) before deciding
  await user.waitFor({ timeout: 20000 }).catch(() => {});
  if (!(await user.isVisible().catch(() => false))) { log('grafana: already logged in'); return; }
  await user.fill(envVal('GRAFANA_ADMIN_USER')); await page.locator('input[name="password"]').fill(envVal('GRAFANA_ADMIN_PASSWORD'));
  await page.getByRole('button', { name: /log in/i }).click(); await page.waitForTimeout(4000);
  if (await page.locator('input[name="user"]').isVisible().catch(() => false)) throw new Error('grafana login failed');
  log('grafana: logged in');
}

async function walk(page, ctx, mark, shot, log, startRec) {
  await grafanaLogin(page, log);   // off camera
  await page.goto(url('/ai-agent'), { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(6000);
  const server = page.locator('.MuiSelect-select').first();
  if (!/Awesomation/i.test(await server.innerText())) {
    await server.dispatchEvent('mousedown'); await page.waitForTimeout(800);
    await page.locator('[role="option"]').filter({ hasText: /Awesomation/i }).first().click(); await page.waitForTimeout(6000);
  }
  await startRec(); mark('page'); await shot('page');
  // Target: host-clone-1 (on camera, short)
  const tsel = page.locator('.MuiFormControl-root:has(label:has-text("Target")) .MuiSelect-select').first();
  const b = await tsel.boundingBox(); await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 25 }); await page.waitForTimeout(400);
  await tsel.dispatchEvent('mousedown'); await page.waitForTimeout(1200);
  const opts = await page.locator('[role="option"]').allInnerTexts(); log('target options: ' + opts.map(o => o.trim()).join(' | ').slice(0, 300));
  const opt = page.locator('[role="option"]').filter({ hasText: TARGET }).first();
  await glide(page, ...(await center(opt)), 900); await page.waitForTimeout(4000);
  log('target now: ' + (await tsel.innerText())); mark('target'); await shot('target');
  // the prompt
  const input = page.getByPlaceholder(/How can I help you\?|Message\.\.\./).first();
  await input.waitFor({ timeout: 30000 });
  const before = ((await page.locator('body').innerText()).match(FOOTER) || []).length;
  await glide(page, ...(await center(input)), 400);
  await input.pressSequentially(PROMPT, { delay: 30 }); await page.waitForTimeout(600);
  await page.keyboard.press('Enter'); mark('ask'); log(`asked: ${PROMPT}`);
  let done = false;
  for (let s = 0; s < 120 && !done; s++) {
    await page.waitForTimeout(2000);
    const txt = await page.locator('body').innerText();
    if ((txt.match(FOOTER) || []).length > before) done = true;
  }
  log(`answer: ${done ? 'done' : 'not finished in 240 s'}`);
  await page.mouse.move(1100, 450, { steps: 12 }); await page.waitForTimeout(4000); mark('canvas'); await shot('canvas');
  // keep fleet-wide names off camera: refuse to go on if one shows
  if (/labox|Smoke Loop Local/i.test(await page.locator('body').innerText())) throw new Error('a fleet-wide name is on screen');
  // Open in Grafana: follow its link in this page
  const link = page.getByRole('link', { name: /open in grafana/i }).first();
  await link.waitFor({ timeout: 20000 }); const href = await link.getAttribute('href');
  await glide(page, ...(await center(link)), 700); mark('open-click');
  await page.goto(new URL(href, page.url()).href, { waitUntil: 'load', timeout: 60000 });
  await page.mouse.move(800, 300, { steps: 10 }); await page.waitForTimeout(9000);
  if (/Log in|Welcome to Grafana/i.test(await page.locator('body').innerText())) throw new Error('grafana login form on screen');
  if (/Failed to load|Internal Server Error|Dashboard not found/i.test(await page.locator('body').innerText())) throw new Error('grafana error on screen');
  mark('grafana'); await shot('grafana');
  // the draft fits one screen: hover today's pass rate, then the incident peak (tooltips)
  await page.mouse.move(898, 244, { steps: 25 }); await page.waitForTimeout(3000); mark('hover-pass'); await shot('hover-pass');
  await page.mouse.move(822, 580, { steps: 25 }); await page.waitForTimeout(3000); mark('hover-incidents'); await shot('hover-incidents');
  await page.waitForTimeout(1500); mark('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR); const page = await ctx.newPage();
  ctx.on('page', p => { if (p !== page) p.close().catch(() => {}); });
  let stop = null; const marks = []; let t0 = Date.now();
  const startRec = async () => { if (!scout) stop = await startRecorder(page, 'grafana'); t0 = Date.now(); };
  const mark = l => { marks.push({ label: l, t: (Date.now() - t0) / 1000 }); };
  const log = s => console.log(redact(s));
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-${name}.png`) });
  try { await walk(page, ctx, mark, shot, log, startRec); } catch (e) { log('ERROR ' + redact(e.message).slice(0, 300)); await shot('error').catch(() => {}); }
  if (!scout) fs.writeFileSync(path.join(OUT, 'grafana.marks.json'), JSON.stringify({ marks }, null, 1));
  if (stop) await stop();
  await ctx.close(); await browser.close();
  console.log(marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
