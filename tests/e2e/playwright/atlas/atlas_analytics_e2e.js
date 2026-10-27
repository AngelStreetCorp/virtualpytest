#!/usr/bin/env node
/**
 * Atlas analytics + Agent Chat post-deploy regression suite (real browser, deployed bundle).
 *
 * Standalone runner (NOT a *.spec.js, so `playwright test` / CI never fires live LLM prompts by accident).
 * Run it through scripts/atlas_analytics_e2e.sh. Docs: docs/agent/ai/ATLAS_ANALYTICS.md "Post-deploy check".
 *
 * Env:
 *   E2E_BASE_URL            default https://virtualpytest.angelstreet.io
 *   E2E_AUTO_SIGN_TOKEN     required (never printed; every logged string is redacted)
 *   E2E_OUT_DIR             screenshots + results.json + summary.md (default /tmp/atlas-e2e-<ts>)
 *   E2E_SERVERS             main,pi (default both)
 *   E2E_PI_SERVER_NAME      default RPI1-server (label in the top-bar server picker)
 *   E2E_HEALTH_RETRY_LIVE   0 = page-load-outage check is expected-fail (bundle older than BUG-0350 / 1176421ef); default hard
 *   E2E_SKIP_HEALTH_RETRY   1 = skip the page-load-outage check
 *   E2E_GRAFANA_USER / E2E_GRAFANA_PASSWORD  Grafana login (the app's auto-sign session does NOT log into Grafana). Without
 *                           them the Grafana panel checks are NA (never PASS); with them every generated dashboard is opened
 *                           in a separate browser context and its panels' queries are asserted. Never printed.
 *   E2E_ONLY                comma list of prompt labels / outage checks (outage-send, outage-hang, outage-load) to run (debug)
 *   PW_NODE_MODULES         node_modules dir holding @playwright/test when this folder has none
 *
 * The suite never executes device actions and never takes control: it only sends chat prompts.
 * Check "GUARD no-device-control" fails if any turn calls a control/execute tool.
 */
const fs = require('fs');
const path = require('path');

function loadPlaywright() {
  const paths = [__dirname, path.join(__dirname, '..')];
  if (process.env.PW_NODE_MODULES) paths.unshift(path.dirname(process.env.PW_NODE_MODULES.replace(/\/$/, '') + '/x'));
  for (const p of [...paths, undefined]) {
    try { return require(p ? require.resolve('@playwright/test', { paths: [p] }) : '@playwright/test'); } catch (e) { /* next */ }
  }
  if (process.env.PW_NODE_MODULES) return require(path.join(process.env.PW_NODE_MODULES, '@playwright/test'));
  throw new Error('@playwright/test not found: run `npm ci` in tests/e2e/playwright or set PW_NODE_MODULES');
}
const { chromium } = loadPlaywright();

const BASE = (process.env.E2E_BASE_URL || 'https://virtualpytest.angelstreet.io').replace(/\/$/, '');
const TOK = process.env.E2E_AUTO_SIGN_TOKEN || '';
if (!TOK) { console.error('E2E_AUTO_SIGN_TOKEN is required'); process.exit(2); }
const OUT = process.env.E2E_OUT_DIR || `/tmp/atlas-e2e-${Date.now()}`;
const SERVERS = (process.env.E2E_SERVERS || 'main,pi').split(',');
const PI_NAME = process.env.E2E_PI_SERVER_NAME || 'RPI1-server';
const ONLY = process.env.E2E_ONLY ? process.env.E2E_ONLY.split(',') : null;
const want = (k) => !ONLY || ONLY.includes(k);
fs.mkdirSync(OUT, { recursive: true });
const GF_USER = process.env.E2E_GRAFANA_USER || '';
const GF_PASS = process.env.E2E_GRAFANA_PASSWORD || '';
const redact = (s) => { let t = String(s).split(TOK).join('***'); if (GF_PASS) t = t.split(GF_PASS).join('***'); return t; };
const clip = (s, n = 160) => redact(s).replace(/\s+/g, ' ').slice(0, n);

const results = []; // {check, server, status, evidence}
function record(check, server, status, evidence) {
  results.push({ check, server, status, evidence: clip(evidence, 300) });
  console.log(`${status.padEnd(6)} [${server}] ${check} :: ${clip(evidence, 300)}`);
}

// ---------------------------------------------------------------- session / capture
const freshEv = () => ({ sent: [], calls: [], results: [], errors: [], messages: [], skills: [], ended: 0 });

async function openSession(browser, server, { beforeLoad } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();
  const s = { ctx, page, server, ev: freshEv(), consoleErrors: [] };
  page.on('console', (m) => { if (m.type() === 'error') s.consoleErrors.push(clip(m.text(), 200)); });
  page.on('websocket', (ws) => {
    ws.on('framesent', (f) => {
      const t = typeof f.payload === 'string' ? f.payload : '';
      if (!t.includes('send_message')) return;
      try {
        const m = JSON.parse(t.slice(t.indexOf('[')))[1];
        s.ev.sent.push({ host_name: m.host_name, device_id: m.device_id, selected_server_name: m.selected_server_name, selected_server_hosts: m.selected_server_hosts || [] });
      } catch (e) { /* not a send_message payload */ }
    });
    ws.on('framereceived', (f) => {
      const t = typeof f.payload === 'string' ? f.payload : '';
      if (!t.startsWith('42/agent') || !t.includes('agent_event')) return;
      let e; try { e = JSON.parse(t.slice(t.indexOf('[')))[1]; } catch (x) { return; }
      if (e.type === 'session_ended') s.ev.ended++;
      else if (e.type === 'message') s.ev.messages.push(String(e.content || ''));
      else if (e.type === 'error') s.ev.errors.push(String(e.content || '').slice(0, 300));
      else if (e.type === 'skill_loaded') s.ev.skills.push(String(e.content || ''));
      else if (e.type === 'tool_call') s.ev.calls.push({ name: e.tool_name, params: e.tool_params });
      else if (e.type === 'tool_result') {
        const r = e.tool_result || {};
        const spec = r.artifact && r.artifact.content_data && r.artifact.content_data.artifact_spec;
        s.ev.results.push({
          name: e.tool_name, isError: !!r.isError, kind: spec && spec.kind, spec,
          text: r.content && r.content[0] && r.content[0].text ? String(r.content[0].text).slice(0, 1500) : '',
        });
      }
    });
  });
  if (beforeLoad) await beforeLoad(page, s);
  return s;
}

// The landing page restores the user's last conversation when there is one (its input says "Message..."),
// and shows the empty landing ("How can I help you?") otherwise. Both are a loaded chat page (BUG-0340 suite
// crash on main: a fresh context opened on a previous conversation and waited 90 s for the landing text).
const LANDING = 'How can I help you?';
const THREAD = 'Message...';

async function loadChat(s) {
  await s.page.goto(`${BASE}/ai-agent?auto_signed=${encodeURIComponent(TOK)}`, { waitUntil: 'domcontentloaded' });
  try {
    await s.page.locator(`[placeholder="${LANDING}"], [placeholder="${THREAD}"]`).first().waitFor({ timeout: 90000 });
  } catch (e) {
    await s.page.screenshot({ path: path.join(OUT, `${s.server}-loadchat-failed.png`) }).catch(() => {});
    throw new Error(`chat input (landing or thread) not visible after 90 s; screenshot ${s.server}-loadchat-failed.png; url ${redact(s.page.url()).replace(/auto_signed=[^&]*/, 'auto_signed=***')}`);
  }
  await s.page.waitForTimeout(3000);
}

async function pickServer(s) {
  if (s.server === 'main') return;
  await s.page.locator('[role=combobox]').first().click({ timeout: 60000 });
  await s.page.getByRole('option', { name: new RegExp(PI_NAME) }).click();
  await s.page.waitForTimeout(6000);
}

const targetCombo = (page) => page.locator('[role=combobox][aria-labelledby*="agent-chat-device-select-label"]');

// Pick the chat's Target (header combobox): the option whose label is `device` on host `host`.
async function selectTarget(s, { host, device }) {
  const c = targetCombo(s.page);
  await c.first().click({ timeout: 30000 }); await s.page.waitForTimeout(800);
  const opts = s.page.locator('[role=option]').filter({ hasText: host });
  const n = await opts.count();
  if (!n) { await s.page.keyboard.press('Escape'); throw new Error(`no Target option for host ${host}`); }
  let pick = 0;
  for (let i = 0; i < n; i++) { if ((await opts.nth(i).innerText()).split('\n')[0].trim() === device) { pick = i; break; } }
  await opts.nth(pick).click(); await s.page.waitForTimeout(1500);
}

async function newChat(s) {
  const landing = s.page.getByPlaceholder(LANDING);
  // Always New Chat: from a restored conversation it gives the empty landing, from the landing it is a no-op.
  const b = s.page.getByRole('button', { name: 'New Chat' });
  if (await b.count()) { await b.first().click(); await s.page.waitForTimeout(1500); }
  try { await landing.waitFor({ timeout: 30000 }); } catch (e) {
    await s.page.screenshot({ path: path.join(OUT, `${s.server}-newchat-failed.png`) }).catch(() => {});
    throw new Error(`New Chat did not open the empty landing within 30 s (screenshot ${s.server}-newchat-failed.png)`);
  }
}

// ---------------------------------------------------------------- DOM snapshot
function domProbe() {
  const vis = (el) => !!el && el.checkVisibility({ checkVisibilityCSS: true, visibilityProperty: true }) && el.getBoundingClientRect().height > 0;
  const rect = (el) => { const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, w: r.width, h: r.height }; };
  const csvBtn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'CSV');
  let root = null;
  if (csvBtn) { root = csvBtn.parentElement; while (root && !root.querySelector('[data-analytics-panel]')) root = root.parentElement; }
  const out = { hasViewer: !!root, panels: document.querySelectorAll('[data-analytics-panel]').length };
  const leafTexts = (scope, re) => [...scope.querySelectorAll('*')].filter((e) => e.children.length === 0 && re.test(e.textContent)).map((e) => e.textContent.trim());
  out.rootText = root ? root.innerText.slice(0, 4000) : '';
  out.scopeNotes = root ? leafTexts(root, /Limited to the \d+ host/) : [];
  out.selectedNotes = root ? leafTexts(root, /Limited to your selected device/) : [];
  const gl = [...document.querySelectorAll('a')].find((a) => a.textContent.trim() === 'Open in Grafana');
  out.grafana = gl ? { href: gl.href, target: gl.target, note: (gl.parentElement && gl.parentElement.innerText) || '' } : null;
  out.missingPreset = /Missing preset filters/i.test(document.body.innerText);
  out.target = (document.querySelector('[role=combobox][aria-labelledby*="agent-chat-device-select-label"]') || {}).innerText || '';
  out.build = ((document.body.innerText.match(/main-\d{4}\.\d\d\.\d\d(-\d+)?/) || [''])[0]);
  // visible error alerts that are NOT inside a tool accordion
  out.visibleErrorAlerts = [...document.querySelectorAll('.MuiAlert-standardError, .MuiAlert-filledError, .MuiAlert-outlinedError')]
    .filter((a) => vis(a) && !a.closest('.MuiAccordion-root')).map((a) => a.innerText.slice(0, 160));
  out.errorTextVisible = [...document.querySelectorAll('[role=alert]')].filter((a) => vis(a) && !a.closest('.MuiAccordion-root')).map((a) => a.innerText.slice(0, 160));
  // x tick vs legend
  let hits = 0, charts = 0; const hitDetail = [];
  for (const wrap of document.querySelectorAll('.recharts-wrapper')) {
    charts++;
    const leg = wrap.querySelector('.recharts-legend-wrapper'); if (!leg) continue;
    const L = leg.getBoundingClientRect();
    for (const t of wrap.querySelectorAll('.recharts-xAxis .recharts-cartesian-axis-tick-value')) {
      const T = t.getBoundingClientRect();
      if (T.height && T.bottom > L.top + 1 && T.top < L.bottom && T.right > L.left && T.left < L.right) { hits++; hitDetail.push(t.textContent.slice(0, 30)); }
    }
  }
  out.charts = charts; out.tickLegendHits = hits; out.tickLegendDetail = hitDetail.slice(0, 5);
  out.yTicks = [...document.querySelectorAll('.recharts-yAxis .recharts-cartesian-axis-tick-value')].map((e) => e.textContent.trim());
  // tables inside analytics panels
  out.tables = [...document.querySelectorAll('[data-analytics-panel] table')].map((t) => {
    let wrap = null, narrow = false, el = t.parentElement;
    const panel = t.closest('[data-analytics-panel]');
    while (el && el !== panel.parentElement) {
      const ox = getComputedStyle(el).overflowX;
      if (!wrap && (ox === 'auto' || ox === 'scroll')) wrap = el;
      if (el.clientWidth && el.clientWidth + 1 < t.scrollWidth && !wrap) narrow = true;
      el = el.parentElement;
    }
    const heads = [...t.querySelectorAll('th')].map((th) => {
      const text = th.innerText.trim(); const words = text.split(/\s+/).filter(Boolean).length;
      const r = document.createRange(); r.selectNodeContents(th);
      const lines = new Set([...r.getClientRects()].filter((q) => q.width > 0).map((q) => Math.round(q.top))).size;
      return { text: text.slice(0, 40), midWord: lines > Math.max(words, 1) };
    });
    return { aria: t.getAttribute('aria-label') || '', hasScrollWrapper: !!wrap, overflowWithoutWrapper: narrow && !wrap,
      scrollW: t.scrollWidth, wrapClientW: wrap ? wrap.clientWidth : null, wrapScrollW: wrap ? wrap.scrollWidth : null, heads };
  });
  // comparison layout
  const cmp = document.querySelector('table[aria-label="comparison"]');
  if (cmp) {
    const svgs = [...document.querySelectorAll('svg.recharts-surface')].filter((s) => s.getBoundingClientRect().height > 50);
    const radar = svgs.find((s) => s.querySelector('.recharts-polar-grid, .recharts-radar')) || svgs[0] || null;
    if (radar) radar.scrollIntoView({ block: 'center' });
    out.cmp = { radar: radar ? rect(radar) : null, isRadar: !!(radar && radar.querySelector('.recharts-polar-grid, .recharts-radar')), table: rect(cmp),
      vw: innerWidth, vh: innerHeight,
      caption: (document.body.innerText.match(/\d+ regression\(s\) in \d+ compared/) || [''])[0],
      oneSided: [...document.querySelectorAll('button')].filter((b) => /with data on one side only/.test(b.textContent)).map((b) => b.textContent.trim()) };
    const c = out.cmp; const r = c.radar, t = c.table;
    if (r) {
      c.leftOrAbove = r.right <= t.left + 2 || r.bottom <= t.top + 2;
      c.fullyVisible = r.top >= 0 && r.left >= 0 && r.bottom <= c.vh && r.right <= c.vw && r.w > 50;
    }
  }
  out.csvButton = !!csvBtn;
  out.lastBubbles = [...document.querySelectorAll('.MuiPaper-root')].map((e) => e.innerText).filter((t) => /^Atlas|→/.test(t)).slice(-2).map((t) => t.slice(0, 600));
  return out;
}

async function csvExport(s, base) {
  const btn = s.page.getByRole('button', { name: 'CSV', exact: true }).last();
  if (!(await btn.count())) return null;
  const [dl] = await Promise.all([s.page.waitForEvent('download', { timeout: 20000 }), btn.click()]);
  const fp = `${base}-${dl.suggestedFilename()}`; await dl.saveAs(fp);
  return fs.readFileSync(fp, 'utf8');
}

async function targetOptions(s) {
  const c = targetCombo(s.page); if (!(await c.count())) return [];
  await c.first().click(); await s.page.waitForTimeout(800);
  const names = await s.page.locator('[role=option]').allInnerTexts();
  await s.page.keyboard.press('Escape'); await s.page.waitForTimeout(400);
  return names.map((n) => n.split('\n')[0].trim()).filter(Boolean);
}

// ---------------------------------------------------------------- links
// HTTP status of a link fetched from Node with the session's cookies (no CORS, redirects followed), so a link to a
// host that answers 404 is a failure here instead of an "unreachable from the page" shrug.
async function fetchStatus(s, href) {
  try {
    const r = await s.ctx.request.get(href, { maxRedirects: 5, failOnStatusCode: false, timeout: 30000 });
    // The app's auto-sign session does not log into Grafana: an unauthenticated fetch ends on /grafana/login with HTTP 200.
    if (r.status() === 200 && /\/grafana\/login/.test(r.url())) return 'login';
    return r.status();
  } catch (e) { return `unreachable: ${clip(e.message, 80)}`; }
}

// Open a generated dashboard the way a logged-in Grafana user would, in its own browser context, and judge the panels:
// (1) All on every variable, (2) the first `host` option selected (the quoted-selection path). Panel queries are told
// apart from variable queries by the request URL (panels carry requestId=SQR..., variable queries do not).
async function grafanaLogin(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/grafana/login`, { waitUntil: 'domcontentloaded' });
  await page.locator('input[name="user"]').fill(GF_USER);
  await page.locator('input[name="password"]').fill(GF_PASS);
  await page.locator('button[type="submit"]').click();
  await page.waitForTimeout(4000);
  const loggedIn = !/\/login/.test(page.url());
  return { ctx, page, loggedIn };
}

async function grafanaOpenAndJudge(page, uid, query, shotBase) {
  const panelRuns = []; const varHost = [];
  const onResp = async (r) => {
    if (!r.url().includes('/api/ds/query')) return;
    let refs = [];
    try {
      const j = await r.json();
      refs = Object.entries(j.results || {}).map(([ref, v]) => ({ ref, status: r.status(), error: v.error || null,
        rows: (v.frames || []).reduce((n, f) => n + ((f.data && f.data.values && f.data.values[0]) ? f.data.values[0].length : 0), 0),
        first: (v.frames && v.frames[0] && v.frames[0].data && v.frames[0].data.values && v.frames[0].data.values[0]) ? v.frames[0].data.values[0][0] : null }));
    } catch (e) { refs = [{ ref: '?', status: r.status(), error: `unparseable response: ${String(e).slice(0, 60)}`, rows: 0 }]; }
    if (/requestId=SQR/.test(r.url())) panelRuns.push(...refs);
    else for (const x of refs) if (x.ref === 'host') varHost.push(x);
  };
  page.on('response', onResp);
  await page.goto(`${BASE}/grafana/d/${uid}?orgId=1&from=now-7d&to=now${query}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(8000);
  for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, 900); await page.waitForTimeout(1200); } // lazy panels below the fold
  await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(4000);
  page.off('response', onResp);
  if (shotBase) await page.screenshot({ path: shotBase, fullPage: true });
  const noData = await page.getByText('No data', { exact: true }).count();
  const errIcons = await page.locator('[data-testid="data-testid Panel status error"], .panel-info-corner--error').count();
  return { url: page.url(), panelQueries: panelRuns.length, errors: panelRuns.filter((x) => x.error || x.status >= 400).map((x) => `${x.ref}: ${clip(x.error || `HTTP ${x.status}`, 100)}`),
    withRows: panelRuns.filter((x) => x.rows > 0).length, rows: panelRuns.reduce((n, x) => n + x.rows, 0), noData, errIcons,
    firstHost: (varHost.find((x) => x.first) || {}).first || null };
}

async function grafanaDeep(browser, uid, shotBase) {
  if (!GF_USER || !GF_PASS) return { skipped: 'Grafana credentials not provided' };
  let g;
  try {
    g = await grafanaLogin(browser);
    if (!g.loggedIn) return { error: 'Grafana login with E2E_GRAFANA_USER/PASSWORD failed' };
    const dj = await g.page.evaluate(async ({ base, uid }) => {
      const r = await fetch(`${base}/grafana/api/dashboards/uid/${uid}`, { credentials: 'include' });
      if (r.status !== 200) return { status: r.status };
      const j = await r.json();
      const list = (j.dashboard.templating || {}).list || [];
      return { status: 200, panels: (j.dashboard.panels || []).filter((p) => p.type !== 'row').length,
        vars: list.map((v) => v.name),
        current: Object.fromEntries(list.map((v) => [v.name, JSON.stringify((v.current || {}).value)])) };
    }, { base: BASE, uid });
    if (dj.status !== 200) return { error: `dashboard ${uid} not readable after login: HTTP ${dj.status}` };
    const all = await grafanaOpenAndJudge(g.page, uid, '', shotBase);
    const out = { expectedPanels: dj.panels, all, json: { status: 200, vars: dj.vars, current: dj.current, panels: dj.panels } };
    if (all.firstHost) out.host = { value: all.firstHost, ...(await grafanaOpenAndJudge(g.page, uid, `&var-host=${encodeURIComponent(all.firstHost)}`, shotBase ? shotBase.replace(/\.png$/, '-host.png') : null)) };
    return out;
  } catch (e) { return { error: `crashed: ${clip(e.message, 120)}` }; } finally { if (g) await g.ctx.close(); }
}

// Verdict of one deep run: {ok, ev}
function judgeGrafanaRun(label, run, expected) {
  const probs = [];
  if (!/\/grafana\/d\//.test(run.url)) probs.push(`ended on ${linkLabel(run.url)}, not the dashboard`);
  if (run.errors.length) probs.push(`${run.errors.length} panel quer${run.errors.length > 1 ? 'ies' : 'y'} errored: ${run.errors.slice(0, 2).join(' / ')}`);
  if (run.errIcons) probs.push(`${run.errIcons} panel error icon(s)`);
  if (run.panelQueries < expected) probs.push(`only ${run.panelQueries} of ${expected} panel queries ran`);
  if (!run.withRows) probs.push('every panel returned 0 rows');
  const ev = `${label}: ${run.panelQueries}/${expected} panel queries, ${run.withRows} with rows (${run.rows} rows), ${run.noData} "No data", ${run.errIcons} error icons`;
  return probs.length ? bad(`${probs.join('; ')} [${ev}]`) : ok(ev);
}
function grafanaPanelChecks(snap, which) {
  const d = snap.gfDeep;
  if (!d) return na('no dashboard uid to open');
  if (d.skipped) return na(d.skipped);
  if (d.error) return bad(d.error);
  if (which === 'all') return judgeGrafanaRun('All on every variable', d.all, d.expectedPanels);
  if (!d.host) return bad('no host option returned by the host variable query');
  const r = judgeGrafanaRun(`host=${d.host.value}`, d.host, d.expectedPanels);
  // one host may legitimately have no data; only errors and missing panels fail this path
  if (!r.ok && !d.host.errors.length && !d.host.errIcons && d.host.panelQueries >= d.expectedPanels && !d.host.withRows) return na(`${r.ev} (this host has no data in 7 days; the quoted selection ran without error)`);
  return r;
}

// The Grafana dashboard link in an answer: absolute, or a /grafana/d/ path (the app redirects it).
function answerGrafanaLink(text) {
  const m = String(text || '').match(/(https?:\/\/[^\s)\]]+)?(\/grafana\/d\/[A-Za-z0-9_-]+[^\s)\]]*)/);
  if (!m) return null;
  return (m[1] ? m[1] : BASE) + m[2];
}
const linkLabel = (href) => String(href).replace(/\?.*/, '');

// ---------------------------------------------------------------- a turn
async function runTurn(s, prompt, label, attempt) {
  await newChat(s);
  s.ev = freshEv();
  if (PROMPTS[label] && PROMPTS[label].target) await selectTarget(s, PROMPTS[label].target);
  const box = s.page.getByPlaceholder('How can I help you?');
  await box.fill(prompt); await box.press('Enter');
  const t0 = Date.now(); let timedOut = false;
  while (s.ev.ended < 1) {
    if (Date.now() - t0 > 240000) { timedOut = true; break; }
    await s.page.waitForTimeout(500);
  }
  await s.page.waitForTimeout(3500);
  const base = path.join(OUT, `${s.server}-${label}${attempt > 1 ? '-retry' : ''}`);
  await s.page.screenshot({ path: base + '.png', fullPage: true });
  const dom = await s.page.evaluate(domProbe);
  const snap = { server: s.server, label, attempt, prompt, ms: Date.now() - t0, timedOut, dom, ev: s.ev, base,
    answer: s.ev.messages.join('\n').trim(), targetOptions: [] };
  try { fs.writeFileSync(base + '-events.json', redact(JSON.stringify({ prompt, sent: s.ev.sent, calls: s.ev.calls, errors: s.ev.errors, answer: s.ev.messages, results: s.ev.results }, null, 1))); } catch (e) { /* evidence only */ }
  if (dom.csvButton && label === 'canvas3') snap.csv = await csvExport(s, base).catch((e) => `ERR ${e}`);
  if (dom.grafana && label === 'canvas3') {
    snap.grafanaStatus = await fetchStatus(s, dom.grafana.href);
    const m = dom.grafana.href.match(/\/grafana\/d\/([A-Za-z0-9_-]+)/);
    snap.dashboardUid = m ? m[1] : null;
    if (snap.dashboardUid) snap.gfDeep = await grafanaDeep(s.ctx.browser(), snap.dashboardUid, base + '-grafana.png');
  }
  if (label === 'selecteddev') {
    // Canvas auto-draft link (button or draft reply): its host/device_name variables must open preselected (BUG-0410).
    const hay = `${dom.grafana ? dom.grafana.href : ''}\n${s.ev.results.filter((r) => r.name === 'create_grafana_draft').map((r) => r.text).join('\n')}`;
    const m = hay.match(/\/grafana\/d\/([A-Za-z0-9_-]+)/);
    snap.dashboardUid = m ? m[1] : null;
    if (snap.dashboardUid) snap.gfDeep = await grafanaDeep(s.ctx.browser(), snap.dashboardUid, base + '-grafana.png');
  }
  if (label.startsWith('dashboard')) {
    // The link as the user gets it (answer text), fetched like a browser would, (the dashboard JSON is read in grafanaDeep, from the logged-in Grafana context).
    const hay = `${snap.answer}\n${s.ev.results.map((r) => r.text).join('\n')}`;
    snap.answerLink = answerGrafanaLink(snap.answer);
    snap.answerLinkStatus = snap.answerLink ? await fetchStatus(s, snap.answerLink) : null;
    const m = hay.match(/\/grafana\/d\/([A-Za-z0-9_-]+)/);
    snap.dashboardUid = m ? m[1] : null;
    if (snap.dashboardUid) snap.gfDeep = await grafanaDeep(s.ctx.browser(), snap.dashboardUid, base + '-grafana.png');
  }
  if (label === 'nonexist') snap.targetOptions = await targetOptions(s);
  return snap;
}

// ---------------------------------------------------------------- checks (pure functions of a snapshot)
const ok = (ev) => ({ ok: true, ev });
const bad = (ev) => ({ ok: false, ev });
const na = (ev) => ({ ok: null, ev });
const renders = (snap) => snap.ev.results.filter((r) => r.name === 'render_analytics_artifact' && !r.isError && r.spec);
const lastSpec = (snap) => { const r = renders(snap); return r.length ? r[r.length - 1].spec : null; };
const specPanels = (spec) => (spec ? (spec.panels || [spec]) : []);
const deviceFilterValues = (params) => {
  const vals = [];
  (function walk(o, key) {
    if (Array.isArray(o)) return o.forEach((x) => walk(x, key));
    if (o && typeof o === 'object') return Object.entries(o).forEach(([k, v]) => walk(v, k));
    if (typeof o === 'string' && /device/i.test(key || '')) vals.push(o);
  })(params && (params.filters || params.panels) ? params : {}, '');
  return vals;
};

const GENERAL = {
  'BUG-0307 no stale error banner': (snap) => {
    const toolErr = snap.ev.results.filter((r) => r.isError).length;
    const vis = snap.dom.visibleErrorAlerts.filter((t) => !/Reconnecting/i.test(t));
    return vis.length ? bad(`visible error alert outside accordions: "${vis[0]}" (tool errors in turn: ${toolErr})`)
      : ok(`no visible error alert outside tool accordions (tool errors in turn: ${toolErr})`);
  },
  'BUG-0311/0313 target is on the selected server': (snap) => {
    const sent = snap.ev.sent[0];
    if (!sent) return bad('no send_message frame captured');
    const inHosts = sent.selected_server_hosts.includes(sent.host_name);
    const notReg = [...snap.ev.errors, ...snap.ev.results.map((r) => r.text)].find((t) => /not registered on the selected server/i.test(t));
    if (!snap.dom.target.trim() || /Select Target/i.test(snap.dom.target)) return bad(`no Target selected (${snap.dom.target})`);
    if (!inHosts) return bad(`host_name ${sent.host_name} not in selected_server_hosts [${sent.selected_server_hosts}]`);
    if (notReg) return bad(`tool error: ${notReg.slice(0, 120)}`);
    const serverOk = snap.server !== 'pi' || sent.selected_server_name === PI_NAME;
    return serverOk ? ok(`Target "${snap.dom.target}" host ${sent.host_name} in [${sent.selected_server_hosts}] on ${sent.selected_server_name}`)
      : bad(`selected_server_name=${sent.selected_server_name}, expected ${PI_NAME}`);
  },
  'BUG-0314 no x tick overlaps a legend': (snap) => (snap.dom.charts === 0 ? na('no chart in turn')
    : snap.dom.tickLegendHits ? bad(`${snap.dom.tickLegendHits} tick(s) intersect legend: ${snap.dom.tickLegendDetail}`) : ok(`${snap.dom.charts} chart(s), 0 overlaps`)),
  'BUG-0316 y axes humanized': (snap) => {
    if (!snap.dom.yTicks.length) return na('no y axis ticks');
    const rawMs = snap.dom.yTicks.filter((t) => /\d{6,}\s*ms/.test(t.replace(/[,\s]/g, (m) => (m === ',' ? '' : m))));
    return rawMs.length ? bad(`raw ms labels: ${rawMs.slice(0, 3)}`) : ok(`y ticks e.g. ${snap.dom.yTicks.slice(0, 5)}`);
  },
  'BUG-0317 canvas tables scroll, headers not split': (snap) => {
    const t = snap.dom.tables.filter((x) => x.aria !== 'comparison');
    if (!t.length) return na('no table in turn');
    const probs = [];
    t.forEach((x, i) => {
      if (x.overflowWithoutWrapper) probs.push(`table${i} overflows with no overflow-x wrapper`);
      if (x.hasScrollWrapper && x.wrapScrollW < x.scrollW - 1) probs.push(`table${i} wrapper scrollW ${x.wrapScrollW} < table ${x.scrollW}`);
      x.heads.filter((h) => h.midWord).forEach((h) => probs.push(`header "${h.text}" wraps mid-word`));
    });
    return probs.length ? bad(probs.join('; ')) : ok(`${t.length} table(s): scrollable wrapper ok, headers: ${t[0].heads.map((h) => h.text).join('|')}`);
  },
  'GUARD no device control': (snap) => {
    const ctl = snap.ev.calls.filter((c) => /take_control|release_control|execute_|navigate_to_node|device_action|press_key|launch_app/i.test(c.name));
    return ctl.length ? bad(`control tool called: ${ctl.map((c) => c.name)}`) : ok(`tools: ${[...new Set(snap.ev.calls.map((c) => c.name))].join(',') || 'none'}`);
  },
};


// A dashboard request is judged on its outcome: ONE create_grafana_draft with 2+ panels, a link in the answer that
// returns HTTP 200, nothing preselected that the user did not ask for. Whether the grafana-dashboard skill or the
// router tool path handled it is reported, not required.
function dashboardChecks(variant) {
  return {
    [`DASHBOARD outcome (${variant}): one create_grafana_draft, 2+ panels, link returns 200`]: (snap) => {
      const draftCalls = snap.ev.calls.filter((c) => c.name === 'create_grafana_draft');
      const probs = []; let loginOnly = false;
      if (draftCalls.length !== 1) probs.push(`${draftCalls.length} create_grafana_draft calls (want 1): ${snap.ev.calls.map((c) => c.name)}`);
      else if (!Array.isArray(draftCalls[0].params && draftCalls[0].params.panels) || draftCalls[0].params.panels.length < 2) probs.push('create_grafana_draft did not get panels=[...] with 2+ panels');
      const res = snap.ev.results.filter((r) => r.name === 'create_grafana_draft');
      if (res.length && res.every((r) => r.isError)) probs.push(`tool error: ${clip(res[0].text, 120)}`);
      if (!snap.answerLink) probs.push(`no /grafana/d/ link in the answer: "${clip(snap.answer, 100)}"`);
      else if (snap.answerLinkStatus === 'login') loginOnly = true;
      else if (snap.answerLinkStatus !== 200) probs.push(`answer link ${linkLabel(snap.answerLink)} returned ${snap.answerLinkStatus} (want HTTP 200)`);
      const route = snap.ev.skills.includes('grafana-dashboard') ? 'via grafana-dashboard skill' : `direct tool path (skills loaded: ${snap.ev.skills.join(',') || 'none'})`;
      if (probs.length) return bad(`${probs.join('; ')} [${route}]`);
      const what = `1 create_grafana_draft with ${draftCalls[0].params.panels.length} panels ${route}; link ${linkLabel(snap.answerLink)}`;
      // a redirect to the Grafana login page is NOT a 200 for the dashboard: it counts only when a logged-in open reached it
      if (loginOnly) return snap.gfDeep && snap.gfDeep.all && /\/grafana\/d\//.test(snap.gfDeep.all.url) ? ok(`${what} -> reachable, login required; opened after Grafana login`)
        : na(`${what} -> reachable, login required (unauthenticated fetch ended on the Grafana login page; ${snap.gfDeep && snap.gfDeep.skipped ? snap.gfDeep.skipped : 'logged-in open failed'})`);
      return ok(`${what} -> 200`);
    },
    [`DASHBOARD nothing preselected unless asked (${variant})`]: (snap) => {
      const call = snap.ev.calls.find((c) => c.name === 'create_grafana_draft');
      if (!call) return bad('no create_grafana_draft call');
      const params = call.params || {};
      const leaves = [params, ...(Array.isArray(params.panels) ? params.panels : [])];
      const probs = [];
      for (const l of leaves) {
        const f = (l && l.filters) || {};
        for (const k of ['device_name', 'host_name']) if (f[k] && (!Array.isArray(f[k]) || f[k].length)) probs.push(`filters.${k}=${JSON.stringify(f[k])}`);
        if (l && l.scope === 'current_device') probs.push('scope=current_device');
      }
      if (/preselected to (the )?current/i.test(snap.answer)) probs.push('answer claims filters were preselected to the current context');
      return probs.length ? bad(`the prompt names no device, but the draft is narrowed: ${probs.join(', ')}`) : ok('no device/host filter or current_device scope in the draft request');
    },
    'DASHBOARD panels run without error (All on every variable)': (snap) => grafanaPanelChecks(snap, 'all'),
    'DASHBOARD panels run without error (one host selected)': (snap) => grafanaPanelChecks(snap, 'host'),
    'DASHBOARD JSON shows the template variables': (snap) => dashboardVariablesJudge(snap),
  };
}

// Template variables of the pushed dashboard, read from the LOGGED-IN Grafana context (the auto-signed app session gets
// 401 from Grafana's API). A variable the user did not ask for must be on All: variables are dashboard-wide, so a
// preset default turned into a selection narrows the other panels away from the chat canvas (BUG-0396).
const ASKED_BY = {
  host: /\b(device|host)s?\b|named|my |selected|current/i,
  device_name: /\b(device|host)s?\b|named|my |selected|current/i,
  user_interface: /interface|\bui\b|web_tv|stb-testop|mobile_app/i,
  environment: /environment|\b(prod|production|dev|staging)\b/i,
  flag: /\b(flag|tag|label)s?\b/i,
};
const dashboardVariablesJudge = (snap) => {
  const g = snap.gfDeep;
  if (!snap.dashboardUid) return bad('no dashboard uid in the answer to fetch');
  if (!g || g.skipped) return na(`${(g && g.skipped) || 'Grafana login not attempted'} (set E2E_GRAFANA_USER/E2E_GRAFANA_PASSWORD)`);
  if (g.error) return bad(`dashboard JSON not readable from the logged-in Grafana context: ${g.error}`);
  const j = g.json;
  const want = ['workspace', 'allowed_devices', 'host', 'device_name', 'user_interface', 'environment', 'flag'];
  const missing = want.filter((v) => !j.vars.includes(v));
  if (missing.length) return bad(`variables missing from the pushed dashboard: ${missing} (has ${j.vars})`);
  const narrowed = Object.keys(ASKED_BY).filter((v) => j.current[v] && !/\$__all|__ALL__/i.test(j.current[v]));
  const unasked = narrowed.filter((v) => !ASKED_BY[v].test(snap.prompt || ''));
  if (unasked.length) return bad(`variables the user did not ask for are not on All: ${unasked.map((v) => `${v}=${j.current[v]}`).join(', ')}`);
  return ok(`uid ${snap.dashboardUid}: variables ${j.vars.join(',')}, ${j.panels} panels; ${narrowed.length ? `selected as asked: ${narrowed}` : 'host/device/interface/environment/flag all on All'}`);
};

const PROMPTS = {
  canvas3: {
    servers: ['main', 'pi'], days: 7,
    text: 'Build a canvas with 3 panels for my selected devices: pass rate by device, KPI averages, and incidents over the last 7 days',
    checks: {
      'BUG-0303/0305 one canvas, 3 panels, one scope note': (snap) => {
        const r = renders(snap).filter((x) => x.kind === 'canvas');
        const asks = /which devices?|what devices?|which device/i.test(snap.answer);
        // "my selected devices" scopes to the Target since BUG-0405, so the note is the selected-device one;
        // without a usable Target it is the server-wide one. Either way it is shown exactly once (BUG-0305).
        const notes = snap.dom.scopeNotes.length + (snap.dom.selectedNotes || []).length;
        const probs = [];
        if (r.length !== 1) probs.push(`${r.length} canvas artifacts (want 1)`);
        else if (specPanels(r[0].spec).length !== 3) probs.push(`${specPanels(r[0].spec).length} panels in spec (want 3)`);
        if (snap.dom.panels !== 3) probs.push(`${snap.dom.panels} panels in DOM (want 3)`);
        if (asks) probs.push('assistant asked which devices');
        if (notes !== 1) probs.push(`scope note shown ${notes}x (want 1)`);
        return probs.length ? bad(probs.join('; ')) : ok(`1 canvas, 3 panels, scope note x1, no device question`);
      },
      'BUG-0320 incident panel grain applied': (snap, p) => {
        const panel = specPanels(lastSpec(snap)).find((x) => /incident/i.test(x.title || ''));
        if (!panel) return bad('no incidents panel in the rendered canvas');
        const rows = (panel.data && panel.data.rows) || [];
        const xKey = (panel.encoding && panel.encoding.x) || 'time';
        const buckets = new Set(rows.map((r) => String(r[xKey]).slice(0, 10))).size; // series (incident_type) multiply rows, not buckets
        const grain = panel.encoding && panel.encoding.time_grain;
        // a 7-day window straddles up to days+1 calendar dates (partial first day)
        if (grain !== 'day') return bad(`time_grain=${grain} (want day); ${rows.length} rows, ${buckets} buckets`);
        return buckets <= p.days + 1 ? ok(`grain=day, ${buckets} day buckets (${rows.length} rows incl. series) for ${p.days} days`) : bad(`${buckets} day buckets > ${p.days}+1 (grain not applied), ${rows.length} rows`);
      },
      'BUG-0330 KPI default interface': (snap) => {
        const t = snap.dom.rootText;
        if (snap.dom.missingPreset || /Missing preset filters/i.test(snap.ev.results.map((r) => r.text).join(' '))) return bad('"Missing preset filters" error shown');
        const hasNote = /Interface:/.test(t) || /No user interface has KPI samples/i.test(t);
        return hasNote ? ok(`note present: ${(t.match(/(Interface:[^\n]*|No user interface has KPI[^\n]*)/) || [''])[0]}`) : bad('neither an "Interface:" note nor the no-KPI note is shown');
      },
      'BUG-0335 canvas keeps all panels': (snap) => {
        const r = renders(snap);
        if (!r.length) return bad('no render_analytics_artifact result');
        const want = Math.max(...r.map((x) => specPanels(x.spec).length));
        return snap.dom.panels >= want ? ok(`${r.length} render(s) in turn, ${snap.dom.panels} panels visible (max spec ${want})`) : bad(`${snap.dom.panels} panels visible but a render had ${want}`);
      },
      'GRAFANA canvas has an Open in Grafana draft link': (snap) => {
        const g = snap.dom.grafana;
        if (!g) {
          const note = snap.ev.results.map((r) => r.text || '').join(' ').match(/Grafana draft not created:[^.\n]*/);
          return bad(note ? `no link; server said: ${note[0]}` : 'no "Open in Grafana" link on the canvas');
        }
        const probs = [];
        if (g.target !== '_blank') probs.push(`link target=${g.target} (want _blank)`);
        if (!/draft · expires|maintained dashboard/.test(g.note)) probs.push(`no draft/expiry label: "${g.note.slice(0, 80)}"`);
        if (probs.length) return bad(probs.join('; '));
        const status = snap.grafanaStatus;
        if (status === 'login') {
          const opened = snap.gfDeep && snap.gfDeep.all && /\/grafana\/d\//.test(snap.gfDeep.all.url);
          return opened ? ok(`link ${linkLabel(g.href)} reachable, login required; opened after Grafana login`)
            : na(`link ${linkLabel(g.href)} reachable, login required (unauthenticated fetch ended on the Grafana login page; ${snap.gfDeep && snap.gfDeep.skipped ? snap.gfDeep.skipped : 'logged-in open failed'})`);
        }
        if (status === 200) return ok(`link ${linkLabel(g.href)} returns HTTP 200 (${g.note.replace(/\s+/g, ' ').trim()})`);
        return bad(typeof status === 'string' ? `link ${linkLabel(g.href)} could not be fetched: ${status}` : `link ${linkLabel(g.href)} returned HTTP ${status}`);
      },
      'GRAFANA canvas draft panels run without error (All on every variable)': (snap) => grafanaPanelChecks(snap, 'all'),
      'GRAFANA canvas draft panels run without error (one host selected)': (snap) => grafanaPanelChecks(snap, 'host'),
      'GRAFANA canvas draft: variables not requested are on All (JSON)': (snap) => dashboardVariablesJudge(snap),
      'EXPORT CSV raw numbers': (snap) => {
        if (!snap.dom.csvButton) return bad('no export toolbar');
        if (!snap.csv || /^ERR/.test(snap.csv)) return bad(`CSV download failed: ${snap.csv}`);
        const cells = snap.csv.split(/\r?\n/).filter((l) => l && !l.startsWith('#')).flatMap((l, i) => (i === 0 ? [] : l.split(',')));
        const withUnit = cells.filter((c) => /^"?\s*-?\d[\d.,]*\s*(ms|min|s|sec|%|h)\s*"?$/i.test(c));
        return withUnit.length ? bad(`${withUnit.length} numeric cells carry units, e.g. ${withUnit.slice(0, 3)}`) : ok(`${cells.length} cells, none with a unit suffix; first lines: ${snap.csv.split(/\r?\n/).slice(0, 2).join(' / ')}`);
      },
    },
  },
  dashboard: {
    servers: ['main', 'pi'],
    text: 'create a Grafana dashboard with pass rate by device and incidents over time',
    checks: dashboardChecks('with the word grafana'),
  },
  dashboardplain: {
    servers: ['main', 'pi'],
    text: 'create a dashboard with pass rate by device and incidents over time',
    checks: dashboardChecks('without the word grafana (skill routing)'),
  },
  tablecanvas: {
    servers: ['main', 'pi'],
    text: 'Build a canvas with 2 panels: the failing test cases as a table, and pass rate by device, over the last 30 days',
    checks: {
      'BUG-0317 canvas tables scroll, headers not split': GENERAL['BUG-0317 canvas tables scroll, headers not split'],
    },
  },
  compare: {
    servers: ['pi'],
    text: 'compare Base and variant1 KPI for stb-testop over the last 30 days and show only regressions over 10%',
    checks: {
      'BUG-0306 comparison layout': (snap) => {
        const c = snap.dom.cmp;
        if (!c) return bad(`no comparison table rendered; answer: ${clip(snap.answer, 100)}`);
        const probs = [];
        if (!c.radar) probs.push('no chart');
        else {
          if (!c.isRadar) probs.push('chart is not a radar');
          if (!c.leftOrAbove) probs.push(`chart not left of/above table (chart ${Math.round(c.radar.left)},${Math.round(c.radar.top)}-${Math.round(c.radar.right)},${Math.round(c.radar.bottom)} vs table ${Math.round(c.table.left)},${Math.round(c.table.top)})`);
          if (!c.fullyVisible) probs.push('chart not fully visible in viewport');
        }
        if (!/regression\(s\) in/.test(c.caption)) probs.push('caption "regression(s) in" missing');
        if (!c.oneSided.length) probs.push('one-sided fold button missing');
        return probs.length ? bad(probs.join('; ')) : ok(`radar ${c.fullyVisible ? 'visible' : ''}, left/above table; caption "${c.caption}"; button "${c.oneSided[0]}"`);
      },
    },
  },
  nonexist: {
    servers: ['pi'], named: ['samsung SM-G998B', 'Phone slot 1'],
    text: 'build a canvas with pass rate, duration trend, and failing cases for devices samsung SM-G998B and Phone slot 1',
    checks: {
      'BUG-0323/0331 nonexistent devices not substituted': (snap, p) => {
        const probs = [];
        const said = /not found|no match|matched nothing|did(?:n't| not) match|couldn'?t find|could not find|no (?:such )?devices?|does(?:n't| not) exist|no data|isn'?t (?:registered|available)|not (?:registered|available)|don'?t (?:exist|have)/i.test(snap.answer);
        if (!said) probs.push(`answer does not say they were not found: "${clip(snap.answer, 120)}"`);
        const named = p.named.map((n) => n.toLowerCase());
        const others = snap.targetOptions.filter((n) => n.length > 2 && !named.some((x) => x.includes(n.toLowerCase()) || n.toLowerCase().includes(x)));
        const titles = renders(snap).map((r) => (r.spec && r.spec.title) || '');
        const hit = titles.filter((t) => others.some((o) => t.toLowerCase().includes(o.toLowerCase())));
        if (hit.length) probs.push(`artifact titled with other devices: ${hit}`);
        const filt = renders(snap).length || snap.ev.calls.length ? snap.ev.calls.flatMap((c) => deviceFilterValues(c.params)) : [];
        const stray = filt.filter((v) => !named.includes(String(v).toLowerCase()));
        if (stray.length) probs.push(`device filter values not named by user: ${[...new Set(stray)]}`);
        return probs.length ? bad(probs.join('; ')) : ok(`said not found; titles ${JSON.stringify(titles)}; filters ${JSON.stringify([...new Set(filt)])}; other devices checked: ${others.length}`);
      },
    },
  },
  selecteddev: {
    servers: ['main'], target: { host: 'host-clone-1', device: 'host' },
    text: 'Build a canvas for my selected devices: pass rate by device, duration trend and incidents over the last 7 days',
    checks: {
      'BUG-0405 "my selected devices" = the Target (scope, note, rows)': (snap, p) => {
        const probs = [];
        const { host } = p.target;
        const device = snap.dom.target.trim(); // the Target's label in the header = its device name (without _Host)
        if (!device || /Select Target/i.test(device)) return bad('no Target selected');
        const rs = renders(snap);
        if (!rs.length) return bad(`no successful render; answer: ${clip(snap.answer, 120)}`);
        const leaves = rs.flatMap((r) => specPanels(r.spec));
        const unscoped = leaves.filter((l) => {
          const rr = (l.provenance && l.provenance.resolved_request) || {};
          const dev = [].concat((rr.filters || {}).device_name || []).map(String);
          const hostF = [].concat((rr.filters || {}).host_name || []).map(String);
          return !(rr.scope === 'current_device' || (dev.length && dev.every((d) => d.replace(/_Host$/, '') === device)) || (hostF.length && hostF.every((h) => h === host)));
        });
        if (unscoped.length) probs.push(`${unscoped.length}/${leaves.length} panel(s) not scoped to the Target (resolved scope: ${unscoped.map((l) => JSON.stringify(((l.provenance || {}).resolved_request || {}).scope)).join(',')})`);
        const notes = leaves.map((l) => (l.options || {}).scope_note || '');
        if (notes.some((n) => /Limited to the \d+ host/.test(n)) || snap.dom.scopeNotes.length) probs.push(`server-wide scope note: ${notes.find((n) => /Limited to the \d+ host/.test(n)) || snap.dom.scopeNotes[0]}`);
        // The header shows the device name without its _Host suffix; the note carries the real device_name.
        const noteFor = new RegExp(`Limited to your selected device ${device.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(_Host)? \\(${host}\\)`);
        if (!notes.some((n) => noteFor.test(n))) probs.push(`no "Limited to your selected device ${device} (${host})" scope note (got ${JSON.stringify([...new Set(notes)])})`);
        const names = new Set();
        leaves.forEach((l) => ((l.data && l.data.rows) || []).forEach((row) => { if (row && row.device_name) names.add(String(row.device_name)); }));
        const stray = [...names].filter((n) => n.replace(/_Host$/, '') !== device);
        if (stray.length) probs.push(`rows for other devices: ${stray.slice(0, 5)}`);
        if (/labox-/i.test(snap.dom.rootText) || /labox-/i.test(snap.answer)) probs.push('labox-* appears in the rendered artifact or the answer');
        const drafts = snap.ev.results.filter((r) => r.name === 'create_grafana_draft' && !r.isError);
        const loose = drafts.filter((r) => !/Limited to your selected device/.test(r.text));
        if (loose.length) probs.push(`${loose.length} Grafana draft(s) not scoped to the Target`);
        return probs.length ? bad(probs.join('; ')) : ok(`${leaves.length} panel(s) all scoped to ${device} (${host}); note present; row devices ${JSON.stringify([...names])}; drafts ${drafts.length}`);
      },
      'BUG-0410 Grafana draft opens with host/device preselected to the Target': (snap, p) => {
        const d = snap.gfDeep;
        if (!d) return na('no Grafana draft link for this canvas');
        if (d.skipped) return na(d.skipped);
        if (d.error) return bad(d.error);
        const cur = (d.json && d.json.current) || {};
        const device = snap.dom.target.trim();
        const hostVal = String(cur.host || ''); const devVal = String(cur.device_name || '');
        const probs = [];
        if (!hostVal.includes(p.target.host) || /__all/.test(hostVal)) probs.push(`host variable is ${hostVal || 'missing'}, want ${p.target.host}`);
        if (!devVal.replace(/_Host/g, '').includes(device) || /__all/.test(devVal)) probs.push(`device_name variable is ${devVal || 'missing'}, want ${device}`);
        return probs.length ? bad(probs.join('; ')) : ok(`host=${hostVal} device_name=${devVal}`);
      },
    },
  },
  kpimain: {
    servers: ['main'],
    text: 'compare Base and variant1 KPI for stb-testop over the last 30 days',
    checks: {
      'BUG-0345 KPI compare with no data: few calls, explains': (snap) => {
        const n = snap.ev.calls.length; const probs = [];
        if (n > 2) probs.push(`${n} tool calls (want <= 2): ${snap.ev.calls.map((c) => c.name)}`);
        if (!/KPI/i.test(snap.answer) || !/(interface|no .*(kpi|data)|only|available|exist|samples)/i.test(snap.answer)) probs.push(`answer does not say what KPI data exists: "${clip(snap.answer, 140)}"`);
        return probs.length ? bad(probs.join('; ')) : ok(`${n} tool call(s); answer: ${clip(snap.answer, 110)}`);
      },
    },
  },
};

// ---------------------------------------------------------------- run prompts with one retry
const rank = { FAIL: 3, FLAKY: 2, PASS: 1, NA: 0 };
async function runPrompt(s, key) {
  const p = PROMPTS[key];
  const checks = { ...GENERAL, ...p.checks };
  const evalAll = (snap) => Object.fromEntries(Object.entries(checks).map(([n, f]) => {
    try { return [n, f(snap, p)]; } catch (e) { return [n, bad(`check crashed: ${e}`)]; }
  }));
  const attempts = [];
  for (let a = 1; a <= 2; a++) {
    let snap;
    try { snap = await runTurn(s, p.text, key, a); } catch (e) {
      snap = { server: s.server, label: key, attempt: a, dom: { panels: 0, scopeNotes: [], tables: [], yTicks: [], charts: 0, visibleErrorAlerts: [] }, ev: freshEv(), answer: '', targetOptions: [], turnError: String(e).slice(0, 200) };
    }
    const broken = snap.turnError || (snap.timedOut && 'turn timed out after 240 s');
    // a turn that never finished fails the prompt-specific checks and the completion check; generic UI checks have nothing to measure
    snap.res = broken ? { ...Object.fromEntries(Object.keys(p.checks).map((n) => [n, bad(broken)])), [`TURN completes (${key})`]: bad(broken) }
      : { ...evalAll(snap), [`TURN completes (${key})`]: ok(`${Math.round(snap.ms / 1000)}s`) };
    attempts.push(snap);
    // only LLM-variance failures are worth a retry; stop when everything that applies passed
    if (!Object.values(snap.res).some((r) => r.ok === false)) break;
  }
  console.log(`      turn ${key} [${s.server}] attempts=${attempts.length} ${attempts.map((x) => Math.round((x.ms || 0) / 1000) + 's').join('+')} calls=${attempts[0].ev.calls.length} build=${attempts[0].dom.build || '?'}`);
  const out = {};
  for (const n of [...Object.keys(checks), `TURN completes (${key})`]) {
    const r = attempts.map((a) => a.res[n]).filter(Boolean);
    if (!r.length || r.every((x) => x.ok === null)) { out[n] = { status: 'NA', ev: r.length ? r[0].ev : 'no measurable turn' }; continue; }
    if (r[0].ok !== false) out[n] = { status: 'PASS', ev: r[0].ev };
    else if (r[1] && r[1].ok === true) out[n] = { status: 'FLAKY', ev: `first attempt failed (${r[0].ev}); retry passed (${r[1].ev})` };
    else out[n] = { status: 'FAIL', ev: r.map((x, i) => `attempt${i + 1}: ${x.ev}`).join(' || ') };
  }
  return { out, attempts };
}

// ---------------------------------------------------------------- outage checks
// The app always appends ?team_id=..., which a '**/path' glob would not match.
const SESSIONS_RE = /\/server\/agent\/sessions(\?|$)/;
const HEALTH_RE = /\/server\/agent\/health(\?|$)/;
async function outageSendCheck(browser, server, warm) {
  const check = `BUG-0340 send during outage is never lost (${warm ? 'existing chat' : 'new chat'})`;
  const sockets = []; let blocked = false;
  const s = await openSession(browser, server, {
    beforeLoad: async (page) => {
      await page.routeWebSocket(/socket\.io/, (ws) => {
        if (blocked) { ws.close(); return; }
        const srv = ws.connectToServer(); sockets.push(ws);
        ws.onMessage((m) => srv.send(m)); srv.onMessage((m) => ws.send(m));
        ws.onClose(() => srv.close()); srv.onClose(() => ws.close());
      });
    },
  });
  try {
    await loadChat(s); await pickServer(s); await newChat(s);
    if (warm) { // a conversation with history: the thread view is where the Reconnecting notice is rendered
      const w = s.page.getByPlaceholder('How can I help you?'); await w.fill('say ok'); await w.press('Enter');
      const tw = Date.now(); while (s.ev.ended < 1 && Date.now() - tw < 90000) await s.page.waitForTimeout(500);
      await s.page.waitForTimeout(1500);
    }
    const marker = `pong-${Math.random().toString(36).slice(2, 7)}`;
    const text = `Reply with exactly the word ${marker} and nothing else`;
    s.ev = freshEv(); // from here on only frames of the blocked send count
    blocked = true;
    await s.page.route('**/socket.io/**', (r) => r.abort());
    await s.page.route(SESSIONS_RE, (r) => (r.request().method() === 'POST' ? r.abort() : r.continue()));
    sockets.forEach((w) => w.close());
    await s.page.waitForTimeout(1500);
    const t0 = Date.now();
    const box = s.page.getByPlaceholder(warm ? 'Message...' : 'How can I help you?');
    await box.fill(text); await box.press('Enter');
    await s.page.waitForTimeout(2500);
    const reconnecting = await s.page.getByText(/Reconnecting/i).first().isVisible().catch(() => false);
    const kept = (await box.inputValue().catch(() => '')) === text || (await s.page.getByText(text, { exact: false }).count()) > 0;
    await s.page.screenshot({ path: path.join(OUT, `${server}-outage-send-${warm ? 'existing' : 'new'}-blocked.png`) });
    await s.page.waitForTimeout(Math.max(0, 10000 - (Date.now() - t0)));
    blocked = false;
    await s.page.unroute('**/socket.io/**'); await s.page.unroute(SESSIONS_RE);
    let delivered = false, visibleErr = '';
    const deadline = Date.now() + 120000;
    while (Date.now() < deadline && !delivered) {
      await s.page.waitForTimeout(1000);
      // Socket frames are only seen on a websocket transport; after an outage socket.io may come back on
      // long-polling, so the answer on screen (the marker twice: our bubble + Atlas's reply) also counts.
      const onScreen = await s.page.getByText(marker, { exact: false }).count().catch(() => 0);
      delivered = (s.ev.sent.length > 0 && s.ev.ended > 0) || onScreen >= 2;
      if (!delivered) {
        const alerts = await s.page.locator('.MuiAlert-root').allInnerTexts().catch(() => []);
        const hard = alerts.find((a) => /Unable to reach|Could not start|stopped responding|not sent/i.test(a));
        visibleErr = hard ? `visible error "${clip(hard, 70)}"` : '';
        if (visibleErr && Date.now() - t0 > 20000) break;
      }
    }
    await s.page.waitForTimeout(1500);
    await s.page.screenshot({ path: path.join(OUT, `${server}-outage-send-${warm ? 'existing' : 'new'}-after.png`) });
    const answered = s.ev.messages.join(' ').includes(marker) || (await s.page.getByText(marker, { exact: true }).count().catch(() => 0)) > 0;
    const probs = [];
    if (!kept) probs.push('typed text not kept/shown');
    if (!reconnecting) probs.push('"Reconnecting" not visible');
    if (!delivered && !visibleErr) probs.push('message neither delivered nor surfaced as an error (silently lost)');
    const status = probs.length ? 'FAIL' : 'PASS';
    record(check, server, status, probs.length ? probs.join('; ') : `text kept, Reconnecting shown, ${delivered ? `delivered after unblock (send frames ${s.ev.sent.length}, answer has marker: ${answered})` : `${visibleErr} (send frames ${s.ev.sent.length})`}`);
  } catch (e) { record(check, server, 'FAIL', `crashed: ${e}`); }
  await s.ctx.close();
}

// BUG-0401: the server ACCEPTS the session-create request but never answers (restart stuck stopping).
// Unlike the refused-connection variant above the socket stays up and the POST just hangs.
async function outageHangCheck(browser, server) {
  const check = 'BUG-0401 send while session create hangs shows Reconnecting and delivers';
  const s = await openSession(browser, server);
  try {
    await loadChat(s); await pickServer(s); await newChat(s);
    const marker = `pong-${Math.random().toString(36).slice(2, 7)}`;
    const text = `Reply with exactly the word ${marker} and nothing else`;
    s.ev = freshEv();
    let release; const gate = new Promise((r) => { release = r; });
    let hung = 0;
    await s.page.route(SESSIONS_RE, async (r) => {
      if (r.request().method() !== 'POST') return r.continue();
      hung++; await gate; return r.continue().catch(() => {});
    });
    const t0 = Date.now();
    const box = s.page.getByPlaceholder('How can I help you?');
    await box.fill(text); await box.press('Enter');
    await s.page.waitForTimeout(5000); // notice must be up within ~3 s of the stalled request
    const reconnecting = await s.page.getByText(/Reconnecting/i).first().isVisible().catch(() => false);
    const kept = (await box.inputValue().catch(() => '')) === text;
    await s.page.screenshot({ path: path.join(OUT, `${server}-outage-hang-blocked.png`) });
    await s.page.waitForTimeout(Math.max(0, 15000 - (Date.now() - t0)));
    release();
    let delivered = false, visibleErr = '';
    const deadline = Date.now() + 120000;
    while (Date.now() < deadline && !delivered) {
      await s.page.waitForTimeout(1000);
      const onScreen = await s.page.getByText(marker, { exact: false }).count().catch(() => 0);
      delivered = (s.ev.sent.length > 0 && s.ev.ended > 0) || onScreen >= 2;
      if (!delivered) {
        const alerts = await s.page.locator('.MuiAlert-root').allInnerTexts().catch(() => []);
        const hard = alerts.find((a) => /Unable to reach|Could not start|stopped responding|not sent/i.test(a));
        visibleErr = hard ? `visible error "${clip(hard, 70)}"` : '';
        if (visibleErr && Date.now() - t0 > 20000) break;
      }
    }
    await s.page.screenshot({ path: path.join(OUT, `${server}-outage-hang-after.png`) });
    const probs = [];
    if (!hung) probs.push('no session-create POST was intercepted (check did not exercise the hang)');
    if (!kept) probs.push('typed text not kept');
    if (!reconnecting) probs.push('"Reconnecting" not visible 5 s into a hung request');
    if (!delivered && !visibleErr) probs.push('message neither delivered nor surfaced as an error');
    record(check, server, probs.length ? 'FAIL' : 'PASS', probs.length ? probs.join('; ') : `Reconnecting shown, text kept, ${delivered ? `delivered after unblock (send frames ${s.ev.sent.length})` : visibleErr}`);
  } catch (e) { record(check, server, 'FAIL', `crashed: ${e}`); }
  await s.ctx.close();
}

async function pageLoadOutageCheck(browser, server) {
  const check = 'PAGE-LOAD health outage recovers without refresh (w13)';
  const hard = process.env.E2E_HEALTH_RETRY_LIVE !== '0'; // BUG-0350 (w13) is on main since 1176421ef
  const s = await openSession(browser, server);
  try {
    let blockedAt = null;
    await s.page.route(HEALTH_RE, (r) => (blockedAt !== null ? r.abort() : r.continue()));
    blockedAt = Date.now();
    s.page.goto(`${BASE}/ai-agent?auto_signed=${encodeURIComponent(TOK)}`, { waitUntil: 'domcontentloaded' }).catch(() => {});
    await s.page.waitForTimeout(10000);
    await s.page.screenshot({ path: path.join(OUT, `${server}-pageload-outage-blocked.png`) });
    blockedAt = null; await s.page.unroute(HEALTH_RE);
    const errTxt = /Backend unavailable|Reconnecting to the server/i;
    const duringBlock = await s.page.getByText(errTxt).first().isVisible().catch(() => false);
    // Recovery = the error notice is gone AND a prompt round-trips (the pre-fix page stays in status 'error').
    let recovered = false, why = ''; const deadline = Date.now() + 60000;
    while (Date.now() < deadline && !recovered) {
      const stillErr = await s.page.getByText(errTxt).first().isVisible().catch(() => false);
      if (!stillErr && (await s.page.getByPlaceholder('How can I help you?').count())) recovered = true; else await s.page.waitForTimeout(1000);
    }
    if (recovered) {
      s.ev = freshEv();
      const box = s.page.getByPlaceholder('How can I help you?');
      await box.fill('say ok'); await box.press('Enter');
      const t1 = Date.now();
      while (s.ev.ended < 1 && Date.now() - t1 < 90000) await s.page.waitForTimeout(500);
      if (s.ev.ended < 1) { recovered = false; why = 'error notice cleared but a prompt got no answer'; }
    } else why = 'error notice still shown / chat unusable 60 s after the health endpoint recovered';
    await s.page.screenshot({ path: path.join(OUT, `${server}-pageload-outage-after.png`) });
    if (recovered) record(check, server, 'PASS', `error notice during outage: ${duringBlock}; recovered without refresh and a prompt round-tripped`);
    else record(check, server, hard ? 'FAIL' : 'XFAIL', `${why} (error notice during outage: ${duringBlock}; ${hard ? 'w13 declared live' : 'expected until w13 is deployed'})`);
  } catch (e) { record(check, server, hard ? 'FAIL' : 'XFAIL', `crashed: ${e}`); }
  await s.ctx.close();
}


// The (check, server) rows this run must produce, from the definitions alone.
function expectedRows(setupFailed) {
  const rows = new Set();
  for (const server of SERVERS) {
    if (setupFailed.has(server)) continue;
    for (const [key, p] of Object.entries(PROMPTS)) {
      if (!p.servers.includes(server) || !want(key)) continue;
      for (const n of [...Object.keys({ ...GENERAL, ...p.checks }), `TURN completes (${key})`]) rows.add(`${n}@@${server}`);
    }
    if (want('outage-send')) for (const warm of [false, true]) rows.add(`BUG-0340 send during outage is never lost (${warm ? 'existing chat' : 'new chat'})@@${server}`);
    if (want('outage-hang')) rows.add(`BUG-0401 send while session create hangs shows Reconnecting and delivers@@${server}`);
  }
  if (want('outage-load') || process.env.E2E_SKIP_HEALTH_RETRY === '1') {
    rows.add(`PAGE-LOAD health outage recovers without refresh (w13)@@${process.env.E2E_SKIP_HEALTH_RETRY === '1' ? 'main' : SERVERS[0]}`);
  }
  return rows;
}

// ---------------------------------------------------------------- main
(async () => {
  const started = Date.now();
  const browser = await chromium.launch();
  const agg = {}; // check -> {server -> status/evidence}
  const meta = { builds: {} };
  const setupFailed = new Set();
  for (const server of SERVERS) {
    const s = await openSession(browser, server);
    try {
      await loadChat(s); await pickServer(s);
      meta.builds[server] = (await s.page.evaluate(domProbe)).build;
      console.log(`== ${server}: bundle ${meta.builds[server] || '?'}`);
    } catch (e) { record('SETUP load chat', server, 'FAIL', String(e)); setupFailed.add(server); await s.ctx.close(); continue; }
    for (const key of Object.keys(PROMPTS)) {
      if (!PROMPTS[key].servers.includes(server) || !want(key)) continue;
      const { out } = await runPrompt(s, key);
      for (const [n, r] of Object.entries(out)) {
            const k = `${n}`;
        agg[k] = agg[k] || {}; (agg[k][server] = agg[k][server] || []).push({ key, ...r });
      }
    }
    await s.ctx.close();
  }
  // every defined check produces a row, NA included (NA rows used to be dropped here, which hid two checks)
  for (const [n, byServer] of Object.entries(agg)) {
    for (const [server, list] of Object.entries(byServer)) {
      const worst = list.reduce((a, b) => ((rank[b.status] || 0) > (rank[a.status] || 0) ? b : a));
      const generalEv = list.length > 1 ? list.map((x) => `${x.key}:${x.status}`).join(' ') + ' | ' + worst.ev : worst.ev;
      record(n, server, worst.status, list.length > 1 ? `${generalEv}` : `[${list[0].key}] ${worst.ev}`);
    }
  }
  for (const server of SERVERS) {
    if (want('outage-send')) { await outageSendCheck(browser, server, false); await outageSendCheck(browser, server, true); }
    if (want('outage-hang')) await outageHangCheck(browser, server);
  }
  if (process.env.E2E_SKIP_HEALTH_RETRY === '1') record('PAGE-LOAD health outage recovers without refresh (w13)', 'main', 'SKIP', 'E2E_SKIP_HEALTH_RETRY=1');
  else if (want('outage-load')) await pageLoadOutageCheck(browser, SERVERS[0]);
  await browser.close();

  // Self-check: rows recorded must equal the checks defined x servers (a defined check can never silently vanish).
  const expected = expectedRows(setupFailed);
  const have = new Set(results.map((r) => `${r.check}@@${r.server}`));
  const missing = [...expected].filter((k) => !have.has(k));
  record('SUITE self-check: one row per defined check x server', SERVERS[0] || 'main', missing.length ? 'FAIL' : 'PASS',
    missing.length ? `${missing.length} defined check row(s) never recorded: ${missing.slice(0, 6).map((k) => k.replace('@@', ' @ ')).join(' | ')}`
      : `${expected.size} defined rows, all recorded (${results.length - 1} rows before this one)`);

  results.sort((a, b) => a.check.localeCompare(b.check) || a.server.localeCompare(b.server));
  const runtime = Math.round((Date.now() - started) / 1000);
  const failed = results.filter((r) => r.status === 'FAIL');
  const md = [`# Atlas analytics post-deploy check`, '', `Base: ${BASE}  | bundle: ${JSON.stringify(meta.builds)}  | runtime: ${runtime}s`, '',
    '| Status | Server | Check | Evidence |', '|---|---|---|---|',
    ...results.map((r) => `| ${r.status} | ${r.server} | ${r.check} | ${r.evidence.replace(/\|/g, '/')} |`), '',
    `PASS ${results.filter((r) => r.status === 'PASS').length}, FLAKY ${results.filter((r) => r.status === 'FLAKY').length}, XFAIL ${results.filter((r) => r.status === 'XFAIL').length}, FAIL ${failed.length}`].join('\n');
  fs.writeFileSync(path.join(OUT, 'results.json'), redact(JSON.stringify({ base: BASE, meta, runtime, results }, null, 1)));
  fs.writeFileSync(path.join(OUT, 'summary.md'), redact(md));
  console.log(`\n${results.length} checks in ${runtime}s -> ${OUT}  (FAIL ${failed.length})`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(redact(e.stack || e)); process.exit(3); });
