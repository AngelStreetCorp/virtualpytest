// Video 32 (drone): beats 1-5 of docs/tasks/video-storyboards/32-drone-tello.md on the Device page of server vpt-pi4:
// Tello TELLO-C5B142 is found, Scan is pressed, the drone pairs and its video starts, the big REC view opens, Take
// control shows the Tello remote. "flight" adds beats 6-8: one take off, a 5 s hover, one landing. No sticks, no flips,
// no Emergency. Every check fails closed (throws), a screenshot goes to out/drone_pre/ per beat, control is released
// in finally, and a drone left airborne by an error is landed first.
// Usage (Mac, lease vpt-pi4 claimed first): PROMO_BASE=https://virtualpytest.angelstreet.io \
//   PROMO_SERVER=https://vpt-pi4.angelstreet.io node drone_capture.js preflight|flight|take
// take = the filmed take (storyboard 32 v2): setup off camera, then the recorder runs Scan -> pair -> REC view -> Control ->
//   take off -> rotate right x3 -> 2 s -> rotate left x3 -> land -> Release. PROMO_START_PAIRED=1: the drone is already paired and live,
//   no Scan beat; film tile -> REC -> Control -> take off -> rotate R/L, Up x2, Down x2, pad forward/back -> land (marks per scene). Output out/drone_pre/drone.mp4 + drone.marks.json
//   (+ take.log with temperature/battery readings). Exit 3 = FAILED_GATE (>= 85 degC, no takeoff, retake after cool-down).
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path'); const cp = require('child_process');
const MODE = process.argv[2];
if (!['preflight', 'flight', 'take', 'ai'].includes(MODE)) { console.error('usage: node drone_capture.js preflight|flight|take|ai'); process.exit(2); }
if (!process.env.PROMO_SERVER) throw new Error('PROMO_SERVER is required (public URL of vpt-pi4)');
const OUT = path.join(__dirname, 'out', 'drone_pre'); fs.mkdirSync(OUT, { recursive: true });
const { url, scrubSecrets, redact, glide, startRecorder, CURSOR, DPR, VIEW_CSS, SERVER } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const SERVER_LABEL = process.env.PROMO_SERVER_LABEL || 'vpt-pi4';   // the Server select entry
// the drone under test (defaults: the first Tello). Second Tello: PROMO_DRONE_TILE=tello-f014a0 PROMO_DRONE_SSID=TELLO-F014A0 PROMO_DRONE_HOST=vpt-nipogi
const DRONE_TILE = (process.env.PROMO_DRONE_TILE || 'tello-c5b142').toLowerCase();   // tile title prefix, case-insensitive
const DRONE_SSID = process.env.PROMO_DRONE_SSID || 'TELLO-C5B142';
const DRONE_HOST = process.env.PROMO_DRONE_HOST || 'vpt-pi4';                        // host in the tile title AND the ssh alias (height read, AP wait, raw land)
const DRONE_DEVICE = process.env.PROMO_DRONE_DEVICE || 'device5';                    // device id where one is needed (not used by the UI flow today)
const DRONE_NAME = 'Tello-' + DRONE_SSID.replace(/^TELLO-/i, '');
const SETUP_TEMP_MAX = Number(process.env.PROMO_SETUP_TEMP_MAX || 80);              // setup gate (the platform's own 85 C takeoff limit is untouched)
console.log(`drone settings: tile "${DRONE_TILE}", SSID ${DRONE_SSID}, host ${DRONE_HOST}, device ${DRONE_DEVICE}, server ${SERVER_LABEL}, setup temperature max ${SETUP_TEMP_MAX} C`);
// Rotate/Up/Down/Move pad are PRESS-AND-HOLD controls (HoldButton: rc values while the pointer is down), so every move is a real mouse hold
const HOLD_ROTATE_MS = 700, PAUSE_ROTATE_MS = 600, HOLD_UD_MS = 800, HOLD_PAD_MS = 800, PAD_PUSH_PX = 35, UD_SETTLE_MS = 1200;
const DEVICE_RE = /TELLO-C5B142|Tello/i;
const t0All = Date.now();
const log = (beat, msg) => console.log(`[${((Date.now() - t0All) / 1000).toFixed(1)}s] beat ${beat}: ${redact(msg)}`);
const fail = (beat, msg) => { throw new Error(`beat ${beat} FAIL: ${msg}`); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const pass = (beat, detail) => { results.push({ beat, verdict: 'PASS', detail }); log(beat, `PASS ${detail}`); };

// ONE badge parser, injected into every page.evaluate (the badge text is split over text nodes: "87","%","95","°C").
// Reads the text nodes of root in document order; battery = number before a "%" node (or inside "87%"), temp likewise for "°C".
function parseBadge(root) {
  const texts = []; const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) { const t = n.textContent.trim(); if (t) texts.push(t); }
  let battery = null, temp = null;
  for (let i = 0; i < texts.length; i++) {
    const t = texts[i], prev = i > 0 ? texts[i - 1] : '';
    let m;
    if (battery === null) {
      if ((m = t.match(/^(\d{1,3})\s*%$/))) battery = parseInt(m[1], 10);
      else if (t === '%' && (m = prev.match(/(\d{1,3})\s*$/))) battery = parseInt(m[1], 10);
    }
    if (temp === null) {
      if ((m = t.match(/^(\d{1,3})\s*°\s*C$/))) temp = parseInt(m[1], 10);
      else if (/^°\s*C$/.test(t) && (m = prev.match(/(\d{1,3})\s*$/))) temp = parseInt(m[1], 10);
    }
  }
  return { battery, temp };
}
// Run a function in the page with parseBadge available (string evaluation, so no CSP eval).
const inPage = (page, fn, arg) => page.evaluate(`(() => { const parseBadge = ${parseBadge.toString()}; return (${fn.toString()})(${JSON.stringify(arg === undefined ? null : arg)}); })()`);

async function poll(fn, timeoutMs, stepMs = 500) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) { const v = await fn().catch(() => null); if (v) return v; await sleep(stepMs); }
  return null;
}

// Stream quality and vpt-stream start time: read only, before any browser action.
function readStreamState() {
  try {
    return cp.execFileSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', DRONE_HOST,
      'cat /var/www/html/stream/active_captures.conf; echo; systemctl show vpt-stream -p ActiveEnterTimestamp'], { encoding: 'utf8', timeout: 25000 }).trim();
  } catch (e) { return `n/a (${String(e.message).split('\n')[0].slice(0, 80)})`; }
}

(async () => {
  const stream = readStreamState();
  log('0', `stream state:\n${stream}`);
  const browser = await chromium.launch({ headless: true });
  const ctx = (MODE === 'take' || MODE === 'ai')
    ? await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true })
    : await browser.newContext({ viewport: { width: 1600, height: 900 } });
  if (MODE === 'take' || MODE === 'ai') { await ctx.addInitScript(CURSOR); await ctx.addInitScript(sv => { try { localStorage.setItem('selectedServer', sv); } catch (e) { /* none */ } }, SERVER); }   // the agent session of /ai-agent starts on vpt-pi4
  const page = await ctx.newPage();
  let controlHeld = false;
  let airborne = false;
  let recStop = null; const takeState = { status: 'RUNNING', marks: [], readings: [] };
  const readHeight = () => page.evaluate(() => {
    const h = [...document.querySelectorAll('span')].find(s => s.textContent.trim() === 'H');
    const m = h && h.parentElement.textContent.match(/^H\s*(-?[\d.]+)\s*m$/);
    return m ? parseFloat(m[1]) : null;
  });
  const remoteLine = () => page.evaluate(() => {
    const main = [...document.querySelectorAll('button')].find(b => /^(take off|land|tap again to take off|taking off…|landing…)$/i.test(b.textContent.trim()));
    if (!main) return null;
    const bottom = main.getBoundingClientRect().bottom;
    const caps = [...document.querySelectorAll('.MuiTypography-caption')].filter(e => e.textContent.trim());
    caps.sort((a, b) => Math.abs(a.getBoundingClientRect().top - bottom) - Math.abs(b.getBoundingClientRect().top - bottom));
    return caps.length ? caps[0].textContent.trim() : null;
  });
  // The C5B142 device tile, selected as in layouts_capture.js; exactly one tile is marked data-drone-tile="1" and every check reads it.
  const snapshot = () => inPage(page, (arg) => {
    document.querySelectorAll('[data-drone-tile]').forEach(e => e.removeAttribute('data-drone-tile'));
    const tiles = Array.from(document.querySelectorAll('[data-device-tile]'));
    const found = tiles.filter(e => Array.from(e.querySelectorAll('h6[aria-label]')).some(h => h.getAttribute('aria-label').toLowerCase().startsWith(arg.tile)));
    if (found.length !== 1) return { tiles: found.length, tileText: '', src: '', loaded: false, battery: null, temp: null, starting: false, chips: [] };
    const [el] = found;
    el.setAttribute('data-drone-tile', '1');
    const media = Array.from(el.querySelectorAll('img, video'));
    media.forEach(m => m.removeAttribute('data-drone-preview'));
    const largest = media.map(m => ({ m, r: m.getBoundingClientRect() })).sort((p, q) => q.r.width * q.r.height - p.r.width * p.r.height)[0];
    const preview = largest && largest.r.width >= 150 ? largest.m : null;
    if (preview) preview.setAttribute('data-drone-preview', '1');
    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
    const { battery, temp } = parseBadge(el);
    return { tiles: 1, tileText: text, src: preview && preview.src ? preview.src.slice(0, 12) : '',
      loaded: !!preview && (preview.tagName === 'IMG' ? preview.complete && preview.naturalWidth > 100 : preview.videoWidth > 100),
      battery, temp, starting: /starting video/i.test(text),
      chips: Array.from(el.querySelectorAll('.MuiChip-root')).map(c => c.textContent.trim()) };
  }, { tile: DRONE_TILE });
  const centerTile = () => page.evaluate(() => { const e = document.querySelector('[data-drone-tile="1"]'); if (e) e.scrollIntoView({ block: 'center' }); }).catch(() => {});
  // Remote panel / dialog reading, split-node tolerant (dialog when open, else the whole body).
  const panelBadge = () => inPage(page, () => parseBadge(document.querySelector('[role="dialog"]') || document.body));
  const batteryPct = async () => { const b = await panelBadge(); return b.battery; };
  const mainBtn = re => page.getByRole('button', { name: re }).first();
  // the remote's main button is a normal <button> with visible text and no aria-label (Take off / Tap again to take off / Land / ...)
  const tBtn = t => page.locator('button').filter({ hasText: new RegExp(`^\\s*${t}\\s*$`) }).first();
  const tVisible = async t => tBtn(t).isVisible().catch(() => false);
  const tEnabled = async t => (await tVisible(t)) && await tBtn(t).isEnabled().catch(() => false);
  const tClick = async (t, fast) => { const el = tBtn(t); if (!fast) await el.scrollIntoViewIfNeeded().catch(() => {}); const b = await el.boundingBox(); if (!b) throw new Error(`"${t}" has no bounding box`); const x = b.x + b.width / 2, y = b.y + b.height / 2; if (!fast) await glide(page, x, y); await page.mouse.click(x, y); };
  const ariaAttached = async l => (await page.locator(`[aria-label="${l}"]`).count().catch(() => 0)) > 0;

  // ---- take mode: setup off camera, then the recorder films beats 1-10 of storyboard 32 v2 ----
  async function takeFlow() {
    const tlogf = path.join(OUT, 'take.log'); fs.writeFileSync(tlogf, '');
    const tlog = m => { const l = `${new Date().toISOString().slice(11, 19)} ${redact(m)}`; fs.appendFileSync(tlogf, l + '\n'); console.log(l); };
    let t0 = Date.now();
    const mark = l => { takeState.marks.push({ label: l, t: (Date.now() - t0) / 1000 }); tlog(`mark ${l} ${((Date.now() - t0) / 1000).toFixed(1)}`); };
    const reading = async (tag, fromTile) => {
      const b = fromTile ? await snapshot() : await panelBadge(); const h = fromTile ? null : await readHeight();
      const r = { tag, battery: b.battery, temp: b.temp, height: h, t: (Date.now() - t0) / 1000 }; takeState.readings.push(r);
      tlog(`reading ${tag}: battery ${b.battery ?? 'n/a'} %, temperature ${b.temp ?? 'n/a'} C, height ${h ?? 'n/a'} m`); return r;
    };
    const tileOkT = s => s.tiles === 1 && s.loaded && s.battery !== null;
    const scanChipT = () => page.locator('[data-drone-tile="1"] .MuiChip-root').filter({ hasText: /^(Scan|Rescan)$/ });
    const glideTo = async loc => { await loc.scrollIntoViewIfNeeded().catch(() => {}); const b = await loc.boundingBox(); if (!b) throw new Error('click target has no bounding box'); await glide(page, b.x + b.width / 2, b.y + b.height / 2); };
    const rotateEnabled = l => page.evaluate(l2 => { const e = document.querySelector(`[aria-label="${l2}"]`); const b = e && (e.matches('button') ? e : e.querySelector('button') || e); return !!b && !b.disabled && b.getAttribute('aria-disabled') !== 'true'; }, l).catch(() => false);
    // hold a control with the real mouse: glide onto its centre, down, hold, up (the up always runs)
    // HIT TEST before every press: the point must hit the target element (or a descendant), else try other points; none = throw, nothing pressed
    const pickPoint = l => page.evaluate(label => {
      const el = document.querySelector(`[aria-label="${label}"]`); if (!el) return { error: 'not found' };
      const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2) return { error: 'no rect' };
      const frac = label === 'Up' ? [[0.5, 0.25], [0.5, 0.5], [0.5, 0.2], [0.3, 0.5], [0.7, 0.5], [0.5, 0.8]]
        : [[0.5, 0.5], [0.5, 0.3], [0.5, 0.2], [0.3, 0.5], [0.7, 0.5], [0.5, 0.8]];
      const tried = [];
      for (const [fx, fy] of frac) {
        const x = r.left + r.width * fx, y = r.top + r.height * fy; const hit = document.elementFromPoint(x, y);
        const hl = hit ? (hit.closest('[aria-label]')?.getAttribute('aria-label') || hit.tagName) : 'none';
        tried.push(`${fx * 100}%/${fy * 100}% -> ${hl}`);
        if (hit && el.contains(hit)) return { x, y, hit: hl, tried };
      }
      return { error: 'no point hits the target', tried };
    }, l);
    const tooltipNow = () => page.evaluate(() => document.querySelector('[role=tooltip]')?.textContent || '').catch(() => '');
    const rotateClick = async (l, holdMs = HOLD_ROTATE_MS) => {
      if (!(await poll(() => rotateEnabled(l), 8000, 200))) throw new Error(`"${l}" not enabled (drone not airborne?)`);
      const pt = await pickPoint(l);
      if (pt.error) throw new Error(`hit test "${l}": ${pt.error} (${(pt.tried || []).join('; ')}) - nothing pressed`);
      await page.mouse.move(pt.x, pt.y, { steps: 28 }); await sleep(300);
      const pt2 = await pickPoint(l); if (pt2.error) throw new Error(`hit test "${l}" after the move: ${pt2.error} - nothing pressed`);
      tlog(`hold "${l}" ${holdMs} ms at (${pt2.x.toFixed(0)},${pt2.y.toFixed(0)}) hit=${pt2.hit}`);
      await page.mouse.move(pt2.x, pt2.y);
      await page.mouse.down();
      try { await sleep(holdMs / 2); tlog(`  tooltip during "${l}": "${await tooltipNow()}"`); await sleep(holdMs / 2); } finally { await page.mouse.up().catch(() => {}); }
    };


    // ---- scene `ai`: after landing, control released, modal closed: the full Atlas chat page of vpt-pi4, a fresh chat, a read-only question ----
    const AI_PROMPT = `Read the telemetry of the drone ${DRONE_NAME} on ${DRONE_HOST} and tell me its battery level, its altitude and its temperature. Only read: do not send any flight command and do not move the drone.`;
    // raw SDK on the Wi-Fi host (read-only `height?` and the safety `land`), from a free source port; never emergency
    const droneRaw = (cmd) => { try { return cp.execFileSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', DRONE_HOST,
      `python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(('',0));s.settimeout(3);s.sendto(b'${cmd}',('192.168.10.1',8889));print(s.recvfrom(64)[0].decode().strip())"`], { encoding: 'utf8', timeout: 20000 }).trim(); } catch (e) { return null; } };
    const droneHeightCm = () => { const r = droneRaw('height?'); const m = r && r.match(/(\d+)\s*dm/i); return m ? parseInt(m[1], 10) * 10 : (r && /^\d+$/.test(r) ? parseInt(r, 10) * 10 : null); };
    const aiHeightGuard = async tag => {
      const h = droneHeightCm(); tlog(`ai height check ${tag}: ${h === null ? 'height unreadable (best effort, continuing)' : h + ' cm'}`);
      if (h !== null && h > 20) { tlog(`drone moved (${h} cm): sending raw SDK land`); const r = droneRaw('land'); tlog(`raw land reply: ${r}`); takeState.status = 'ABORTED_AI_MOVED'; throw new Error(`ABORTED_AI_MOVED: height ${h} cm after landing (raw land sent)`); }
    };
    const aiScene = async () => {
      // close the REC modal (the Ask AI button is not mounted while it is open)
      const closeBtn = page.locator('button:has([data-testid="CloseIcon"])').last();
      if (await closeBtn.isVisible().catch(() => false)) { await glideTo(closeBtn); await sleep(1500); }
      await aiHeightGuard('before chat');
      mark('ai-start');
      await page.goto(url('/ai-agent'), { waitUntil: 'load', timeout: 120000 }); await sleep(6000);
      await scrubSecrets(page);
      const srv = (await page.locator('.MuiFormControl-root:has(label:has-text("Server")) .MuiSelect-select').first().innerText().catch(() => '')).trim();
      if (srv !== SERVER_LABEL) { takeState.status = 'AI_FAILED'; throw new Error(`ai: the chat page shows server "${srv}", not ${SERVER_LABEL}`); }
      await glideTo(page.getByRole('button', { name: 'New Chat' })); await sleep(1500);
      const inp = page.locator('textarea[placeholder="How can I help you?"], input[placeholder="How can I help you?"]').first();
      await glideTo(inp);
      await page.keyboard.type(AI_PROMPT, { delay: 12 }); await sleep(800);
      mark('ai-sent'); await page.keyboard.press('Enter');
      const tSend = Date.now(); let started = false, stable = 0, reply = '', lastGuard = Date.now();
      const replyOf = async () => { const txt = await page.evaluate(() => document.body.innerText || ''); let i = txt.lastIndexOf('View Reasoning'); i = i >= 0 ? i + 'View Reasoning'.length : Math.max(0, txt.lastIndexOf('do not move the drone.') + 22); return txt.slice(i).split(/What went wrong|©/)[0].replace(/\s+\n/g, '\n').trim(); };
      while (Date.now() - tSend < 60000) {
        await sleep(2000);
        const processing = await page.locator('[data-testid="StopIcon"]').count().catch(() => 0) > 0;
        if (processing) started = true;
        reply = await replyOf();
        if (Date.now() - lastGuard > 12000) { lastGuard = Date.now(); await aiHeightGuard('during chat'); }
        if ((started || Date.now() - tSend > 8000) && !processing && reply.length > 20) { stable++; if (stable >= 2) break; } else stable = 0;
      }
      const secs = ((Date.now() - tSend) / 1000).toFixed(1);
      if (stable < 2) { takeState.status = 'AI_FAILED'; await page.screenshot({ path: path.join(OUT, 'ai-fail.png') }).catch(() => {}); throw new Error(`ai: no finished reply within 60 s (last text "${reply.slice(0, 200)}")`); }
      await scrubSecrets(page); mark('ai-reply');
      await page.screenshot({ path: path.join(OUT, 'ai-reply.png') });
      await sleep(8000);
      reply = await replyOf();
      const hasBat = /\d{1,3}\s*%/.test(reply), hasTemp = /\d{2,3}\s*(°|deg|C)/i.test(reply), hasAlt = /\d+(\.\d+)?\s*(m\b|cm\b|metre|meter)|(altitude|height)\D{0,20}\d/i.test(reply);
      const redBlock = await page.locator('[data-testid="ErrorIcon"], [data-testid="ErrorOutlineIcon"]').count().catch(() => 0) > 0;
      takeState.aiReply = { seconds: parseFloat(secs), text: reply.slice(0, 1500), battery: hasBat, temperature: hasTemp, altitude: hasAlt, errorUi: redBlock };
      tlog(`ai reply after ${secs} s: battery ${hasBat}, temperature ${hasTemp}, altitude ${hasAlt}, error block ${redBlock}; text: ${reply.replace(/\s+/g, ' ').slice(0, 600)}`);
      mark('ai-end');
      await aiHeightGuard('after chat');
      if (!hasBat || !hasTemp || redBlock || /failed|\b401\b|unauthori/i.test(reply)) { takeState.status = 'AI_FAILED'; throw new Error(`ai: reply check failed (battery ${hasBat}, temperature ${hasTemp}, error ${redBlock})`); }
    };

    // ---- mode `ai`: only the Atlas telemetry scene, no flight, no control. Waits (max 300 s) for a paired, live tile, then films at once ----
    const aiRun = async () => {
      tlog('WAITING_FOR_PAIRING'); process.stdout.write('WAITING_FOR_PAIRING\n');
      const wEnd = Date.now() + 300000; let s0 = null, centred = false;
      while (Date.now() < wEnd && !s0) {
        const s = await snapshot().catch(() => null);
        if (s && s.tiles === 1 && !centred) { await centerTile(); centred = true; }
        if (s && tileOkT(s)) { const s2 = await snapshot().catch(() => null); if (s2 && tileOkT(s2)) { s0 = s2; break; } }
        await sleep(1500);
      }
      if (!s0) { takeState.status = 'SETUP_FAILED'; throw new Error('setup: the tile did not become paired + live within 300 s'); }
      tlog(`PAIRED_SEEN ${s0.battery} ${s0.temp}`); process.stdout.write(`PAIRED_SEEN ${s0.battery} ${s0.temp}\n`);
      await centerTile(); await page.mouse.move(1500, 60);
      recStop = await startRecorder(page, 'drone_ai'); t0 = Date.now();
      tlog('RECORDING_STARTED'); process.stdout.write('RECORDING_STARTED\n');
      await aiScene();
      await recStop(); recStop = null;
      takeState.status = 'OK'; results.push({ beat: 12, verdict: 'PASS', detail: 'ai clip complete' });
    };

    // ---- variant PROMO_START_PAIRED=1: the drone is already paired and live; no Scan beat, the time goes to the manoeuvres ----
    const pairedRun = async () => {
      const WAIT = process.env.PROMO_WAIT_PAIRED === '1';
      let s0 = null;
      if (WAIT) {
        // launched BEFORE the owner pairs: poll the tile (max 300 s) until paired + live and cool enough, then film at once
        tlog('WAITING_FOR_PAIRING'); process.stdout.write('WAITING_FOR_PAIRING\n');
        const wEnd = Date.now() + 300000; let sawHot = null, lastHot = 0, centred = false;
        while (Date.now() < wEnd && !s0) {
          const s = await snapshot().catch(() => null);
          if (s && s.tiles === 1 && !centred) { await centerTile(); centred = true; }
          if (s && tileOkT(s) && s.temp !== null) {
            if (s.temp < SETUP_TEMP_MAX) {
              const s2 = await snapshot().catch(() => null);   // re-read once: still true?
              if (s2 && tileOkT(s2) && s2.temp !== null && s2.temp < SETUP_TEMP_MAX) { s0 = s2; break; }
            } else { sawHot = s.temp; if (Date.now() - lastHot >= 15000) { lastHot = Date.now(); tlog(`too hot ${s.temp}, waiting`); } }
          }
          await sleep(1500);
        }
        if (!s0 && sawHot === null) { takeState.status = 'SETUP_FAILED'; throw new Error('setup: the tile did not become paired + live within 300 s'); }
        if (!s0) { takeState.status = 'TEMP_TOO_HIGH'; takeState.reason = `tile temperature ${sawHot} C for 300 s`; tlog(`TEMP_TOO_HIGH ${sawHot} C (max ${SETUP_TEMP_MAX})`); process.stdout.write('TEMP_TOO_HIGH\n'); results.push({ beat: 0, verdict: 'FAILED_GATE', detail: takeState.reason }); return; }
        tlog(`PAIRED_SEEN ${s0.battery} ${s0.temp}`); process.stdout.write(`PAIRED_SEEN ${s0.battery} ${s0.temp}\n`);
      } else {
      s0 = await poll(async () => { const s = await snapshot(); return tileOkT(s) ? s : null; }, 60000, 1000);
      if (!s0) { takeState.status = 'SETUP_FAILED'; const st = await snapshot().catch(() => ({ tileText: '' })); throw new Error(`setup: tile not paired + live (battery + loaded preview) within 60 s (tile "${(st.tileText || '').slice(0, 200)}")`); }
      if (s0.temp !== null && s0.temp >= SETUP_TEMP_MAX) {
        takeState.status = 'TEMP_TOO_HIGH'; takeState.reason = `tile temperature ${s0.temp} C`;
        tlog(`TEMP_TOO_HIGH ${s0.temp} C (max ${SETUP_TEMP_MAX})`); process.stdout.write('TEMP_TOO_HIGH\n'); results.push({ beat: 0, verdict: 'FAILED_GATE', detail: takeState.reason }); return;
      }
      }
      await centerTile(); await page.mouse.move(1500, 60); if (!WAIT) await sleep(800);
      tlog(`setup done: tile battery ${s0.battery} %, temperature ${s0.temp ?? 'n/a'} C`);
      const hotCheck = async tag => {
        const b = await panelBadge(); tlog(`hot check ${tag}: temperature ${b.temp ?? 'n/a'} C`);
        if (b.temp !== null && b.temp >= 90) { takeState.status = 'ABORTED_HOT'; mark('aborted-hot'); throw new Error(`ABORTED_HOT: ${b.temp} C while airborne (safety Land follows)`); }
      };
      const heightNow = async () => (await readHeight()) ?? 0;
      // the status strip updates every ~2 s and the drone needs 1-2 s to move: read until two readings 1.2 s apart agree, max 4.5 s
      const readStableHeight = async () => {
        const t1 = Date.now(); const hist = []; let last = await heightNow(); hist.push([Date.now(), last]);
        while (Date.now() - t1 < 4500) {
          await sleep(400); last = await heightNow(); hist.push([Date.now(), last]);
          const old = hist.filter(([t]) => Date.now() - t >= 1200).pop();
          if (old && Math.abs(last - old[1]) < 0.05) return last;
        }
        return last;
      };
      const pushPad = async (dir, name) => {
        if (!(await poll(() => rotateEnabled('Move pad'), 8000, 200))) throw new Error('"Move pad" not enabled');
        const b = await page.locator('[aria-label="Move pad"]').first().boundingBox(); if (!b) throw new Error('"Move pad" has no bounding box');
        const pt = await pickPoint('Move pad'); if (pt.error) throw new Error(`hit test "Move pad": ${pt.error} (${(pt.tried || []).join('; ')}) - nothing pressed`);
        const cx = pt.x, cy = pt.y, d = Math.min(PAD_PUSH_PX, b.y + b.height - cy - 4, cy - b.y - 4) * dir;   // stays inside the pad
        await page.mouse.move(cx, cy, { steps: 28 }); await sleep(400);
        tlog(`pad ${name}: down at (${cx.toFixed(0)},${cy.toFixed(0)}) hit=${pt.hit}, move ${d.toFixed(0)} px, hold ${HOLD_PAD_MS} ms`);
        await page.mouse.down();
        try { await page.mouse.move(cx, cy + d, { steps: 8 }); await sleep(HOLD_PAD_MS); } finally { await page.mouse.up().catch(() => {}); }
      };
      recStop = await startRecorder(page, 'drone'); t0 = Date.now();
      tlog('RECORDING_STARTED'); process.stdout.write('RECORDING_STARTED\n');
      // tile: live tile with its badge, 3 s
      mark('tile-start'); await sleep(3000);
      if (!tileOkT(await snapshot())) throw new Error('tile: preview/battery lost during the hold');
      mark('tile-end');
      // rec: real click on the centre of the tile's largest media
      await centerTile(); await sleep(500);
      const imgBox = await page.locator('[data-drone-preview="1"]').first().boundingBox().catch(() => null);
      if (!imgBox) throw new Error('rec: tile preview not clickable');
      mark('rec-start');
      await glide(page, imgBox.x + imgBox.width / 2, imgBox.y + imgBox.height / 2, 700);
      const recOpen = () => page.evaluate(() => {
        const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
        return [...document.querySelectorAll('button')].some(b => vis(b) && b.textContent.trim() === 'Control') && /Last 24h/.test(document.body.innerText || '') && !/\/monitoring\//.test(location.href);
      });
      if (!(await poll(recOpen, 20000, 250))) throw new Error('rec: REC view did not open within 20 s');
      await scrubSecrets(page); await sleep(3000); mark('rec-end');
      // control: remote visible 3 s; gate again
      mark('control-start');
      await glideTo(page.locator('button').filter({ hasText: /^\s*Control\s*$/ }).first()); controlHeld = true;
      const remoteReady = async () => /Tello Remote/.test(await page.evaluate(() => document.body.innerText || '')) && await tVisible('Take off') && await tVisible('Release');
      if (!(await poll(remoteReady, 25000, 250))) throw new Error('control: Tello remote not ready within 25 s');
      await scrubSecrets(page);
      const r5 = await reading('remote open');
      tlog(`aria-labels attached: ${(await Promise.all(['Up', 'Down', 'Rotate left', 'Rotate right', 'Move pad', 'Emergency stop'].map(async l => `${l}=${await ariaAttached(l)}`))).join(', ')}`);
      if (r5.temp === null || r5.temp >= 85) {
        takeState.status = 'FAILED_GATE'; takeState.reason = `temperature ${r5.temp ?? 'unreadable'} C`;
        console.log(`TEMP GATE ${r5.temp} C: no take off, take marked FAILED_GATE`);
        await sleep(1500); mark('gate-stop'); await recStop(); recStop = null;
        const rel = tBtn('Release'); if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); await sleep(2500); console.log('control released'); }
        controlHeld = false; results.push({ beat: 5, verdict: 'FAILED_GATE', detail: takeState.reason }); return;
      }
      await sleep(3000); mark('control-end');
      // takeoff: ONE click (airborne from the click), optional "Tap again", hold 3 s
      await reading('before take off');
      airborne = true; mark('takeoff-start');
      await tClick('Take off');
      if (await poll(() => tVisible('Tap again to take off'), 1500, 50)) await tClick('Tap again to take off', true);
      if (!(await poll(() => tVisible('Land'), 12000, 200))) throw new Error('takeoff: no "Land" button within 12 s');
      if (!(await poll(async () => (await readHeight()) > 0, 10000, 300))) throw new Error('takeoff: height did not rise above 0 within 10 s');
      await sleep(3000); await reading('hover'); await hotCheck('takeoff'); mark('takeoff-end');
      // rotate right x3, 2 s hold; rotate left x3 (the hold is the wait), 2 s hold
      mark('rotate_right-start');
      for (let i = 0; i < 3; i++) { await rotateClick('Rotate right'); await sleep(PAUSE_ROTATE_MS); }
      await sleep(2000); mark('rotate_right-end'); await hotCheck('rotate right');
      mark('rotate_left-start');
      for (let i = 0; i < 3; i++) { await rotateClick('Rotate left'); await sleep(PAUSE_ROTATE_MS); }
      await sleep(2000); mark('rotate_left-end'); await reading('after rotations'); await hotCheck('rotate left');
      // UP first (up to 2 x 800 ms), then DOWN: independent of the hover height
      // the status strip lags the real motion by up to ~5-6 s: heights are LOG-ONLY here; each move waits a fixed 3.5 s on camera.
      // Pass criterion for the moves: every press hit its control (hit test) and no exception.
      mark('up-start');
      let hLast = await readStableHeight(); const h0 = hLast; tlog(`vertical moves: h0 = ${h0} m (last known)`);
      if (hLast >= 1.0) tlog(`up: skipped, last known height ${hLast} m >= 1.0 m`);
      else { await rotateClick('Up', HOLD_UD_MS); await sleep(3500); hLast = await readStableHeight(); tlog(`up 1: ${h0} -> ${hLast} m (log only, strip may lag)`); }
      mark('up-end'); await hotCheck('up');
      mark('down-start');
      const downPresses = hLast >= 1.0 ? 2 : 1;
      for (let i = 0; i < downPresses; i++) {
        if (hLast <= 0.4) { tlog(`down ${i + 1}: skipped, last known height ${hLast} m <= 0.4 m`); break; }
        await rotateClick('Down', HOLD_UD_MS); await sleep(3500);
        const hs = await heightNow(); tlog(`down ${i + 1}: last known ${hLast} -> ${hs} m (log only, strip may lag)`); hLast = hs;
      }
      await sleep(4000); tlog(`down group done: height ${await readStableHeight()} m (log only)`);
      mark('down-end'); await hotCheck('down');
      // forward then back: short pad pushes, 0.8 s, 2 s hold each
      tlog(`pad: stable height before forward ${await readStableHeight()} m`);
      mark('forward-start'); await pushPad(-1, 'forward'); await sleep(3500); mark('forward-end'); tlog(`pad: stable height after forward ${await readStableHeight()} m`); await hotCheck('forward');
      mark('back-start'); await pushPad(1, 'back'); await sleep(3500); mark('back-end'); tlog(`pad: stable height after back ${await readStableHeight()} m`); await reading('after pad'); await hotCheck('back');
      // land, hold 4 s, THEN release
      mark('land-start');
      await tClick('Land');
      const landedNow = async () => (await tEnabled('Take off')) && (((await readHeight()) ?? 0) <= 0.15);
      let down = await poll(landedNow, 15000, 300);
      if (!down && await tVisible('Land')) { await tClick('Land'); down = await poll(landedNow, 15000, 300); }
      if (!down) throw new Error('land: not landed within 30 s (Take off not enabled / height not ~0)');
      airborne = false; await reading('landed');
      await sleep(4000); mark('land-end');
      await glideTo(tBtn('Release')); controlHeld = false; await sleep(2000); mark('end');
      if (process.env.PROMO_AI_SCENE !== '0') await aiScene();   // scene ai (telemetry only); PROMO_AI_SCENE=0 switches it off
      await recStop(); recStop = null;
      takeState.status = 'OK'; results.push({ beat: 10, verdict: 'PASS', detail: 'take complete (paired start)' });
    };

    // SETUP, off camera: page, Server = vpt-pi4, tile centred, one assert chain
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 }); await sleep(4000);
    const sel = page.locator('.MuiFormControl-root:has(label:has-text("Server")) .MuiSelect-select').first();
    await sel.waitFor({ timeout: 30000 });
    if ((await sel.innerText()).trim() !== SERVER_LABEL) {
      await sel.click(); await sleep(800);
      await page.locator('[role="option"]').filter({ hasText: new RegExp(`^${SERVER_LABEL}`) }).first().click({ timeout: 10000 });
    }
    if (!(await poll(async () => (await sel.innerText()).trim() === SERVER_LABEL, 60000, 1000))) throw new Error(`Server select never showed "${SERVER_LABEL}"`);
    if (process.env.PROMO_WAIT_PAIRED === '1') await page.mouse.move(800, 300); else { await sleep(9000); await page.mouse.move(800, 300); await sleep(15000); }
    await scrubSecrets(page);
    if (MODE === 'ai') { await aiRun(); return; }
    if (process.env.PROMO_START_PAIRED === '1' || process.env.PROMO_WAIT_PAIRED === '1') { await pairedRun(); return; }
    // wait (max 90 s) for the automatic scan window to end: tile says "Drone not found" and has the Scan chip
    const scanChipOn0 = s => s.tiles === 1 && s.chips.some(c => /^(Scan|Rescan)$/.test(c));
    let s0 = null;
    const wEnd = Date.now() + 90000;
    while (Date.now() < wEnd) {
      s0 = await snapshot().catch(() => null);
      if (s0 && s0.tiles === 1 && (tileOkT(s0) || (/drone not found/i.test(s0.tileText) && scanChipOn0(s0)))) break;
      await sleep(1000);
    }
    if (!s0 || s0.tiles !== 1) throw new Error(`expected exactly one device tile for ${DRONE_NAME}`);
    if (tileOkT(s0) || !/drone not found/i.test(s0.tileText) || !scanChipOn0(s0)) { takeState.status = 'SETUP_FAILED'; throw new Error(`setup: tile is not "Drone not found" + Scan chip within 90 s (paired/connected or still scanning; tile "${s0.tileText.slice(0, 200)}"): power the drone off and retry`); }
    if (await scanChipT().count() !== 1) throw new Error('setup: expected exactly one Scan chip inside the Tello tile');
    await centerTile(); await page.mouse.move(1500, 60); await sleep(500);
    tlog(`setup done, tile text: "${s0.tileText.slice(0, 200)}"`);
    // the owner powers the drone on now; wait for its Wi-Fi on the host (max 120 s)
    tlog('POWER_ON_NOW'); process.stdout.write('POWER_ON_NOW\n');
    const apSeen = async () => { try { const o = cp.execFileSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', DRONE_HOST,
      `sudo -n nmcli device wifi rescan >/dev/null 2>&1; nmcli -t -f SSID device wifi list | grep -c "^${DRONE_SSID}"`], { encoding: 'utf8', timeout: 20000 }); return parseInt(o.trim(), 10) > 0; } catch (e) { return false; } };
    if (!(await poll(apSeen, 120000, 2000))) { takeState.status = 'BLOCKED'; throw new Error(`BLOCKED: the drone Wi-Fi ${DRONE_SSID} never appeared within 120 s (no control taken)`); }
    tlog('AP_SEEN'); process.stdout.write('AP_SEEN\n');
    await sleep(4000);   // AP ready
    const s0b = await snapshot();
    if (s0b.tiles !== 1 || tileOkT(s0b) || !/drone not found/i.test(s0b.tileText) || !scanChipOn0(s0b)) { takeState.status = 'SETUP_FAILED'; throw new Error(`setup: the tile changed after the AP appeared (tile "${s0b.tileText.slice(0, 200)}")`); }
    await centerTile();

    // FILM
    recStop = await startRecorder(page, 'drone'); t0 = Date.now();
    tlog('RECORDING_STARTED'); process.stdout.write('RECORDING_STARTED\n');
    // beat 1: tile not paired, hold 3 s (text read scoped to the tile)
    mark('beat1-start'); await sleep(3000);
    const s1 = await snapshot(); if (s1.tiles !== 1 || !s1.chips.some(c => /^(Scan|Rescan)$/.test(c))) throw new Error(`beat 1: tile is not in the not-paired state ("${s1.tileText.slice(0, 160)}")`);
    mark('beat1-end');
    // beat 2: Scan on the tile; one retry after "Could not pair" (the drone may power on a few seconds late)
    let attempts = 0, paired = null;
    while (!paired) {
      attempts++; await centerTile();
      mark(`beat2-action${attempts > 1 ? attempts : ''}`);
      await glideTo(scanChipT().first());
      if (!(await poll(async () => { const s = await snapshot(); return s.tiles === 1 && /Scanning/i.test(s.tileText) ? s : null; }, 8000, 250))) throw new Error('beat 2: "Scanning" did not appear in the tile within 8 s');
      mark(`beat2-picked${attempts > 1 ? attempts : ''}`);
      paired = await poll(async () => { const s = await snapshot(); return tileOkT(s) ? s : null; }, 60000, 300);
      if (paired) break;
      const st = await snapshot(); tlog(`beat 2: attempt ${attempts} ended: "${st.tileText.slice(0, 160)}"`);
      if (attempts >= 2 || !/could not pair|drone not found/i.test(st.tileText)) { takeState.status = 'BLOCKED'; throw new Error(`beat 2: BLOCKED: tile did not pair after ${attempts} Scan click(s)`); }
      await sleep(6000);
    }
    // beat 3: tile live with battery badge and preview loaded
    await scrubSecrets(page); await centerTile(); await page.mouse.move(1500, 60, { steps: 6 });
    mark('beat3-loaded'); await reading('tile after pair', true);
    await sleep(4000);
    const s3 = await snapshot(); if (!tileOkT(s3)) throw new Error('beat 3: tile preview/battery lost during the hold');
    mark('beat3-end');
    // beat 4: real click on the centre of the tile's largest media -> REC view
    await centerTile(); await sleep(500);
    const imgBox = await page.locator('[data-drone-preview="1"]').first().boundingBox().catch(() => null);
    if (!imgBox) throw new Error('beat 4: tile preview not clickable');
    mark('beat4-click');
    await glide(page, imgBox.x + imgBox.width / 2, imgBox.y + imgBox.height / 2, 700);
    const recOpen = () => page.evaluate(() => {
      const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
      return [...document.querySelectorAll('button')].some(b => vis(b) && b.textContent.trim() === 'Control') && /Last 24h/.test(document.body.innerText || '') && !/\/monitoring\//.test(location.href);
    });
    if (!(await poll(recOpen, 20000, 250))) throw new Error('beat 4: REC view did not open within 20 s');
    await scrubSecrets(page); mark('beat4-open'); await sleep(3000); mark('beat4-end');
    // beat 5: Control -> remote visible; temperature gate
    mark('beat5-click');
    await glideTo(page.locator('button').filter({ hasText: /^\s*Control\s*$/ }).first()); controlHeld = true;
    const remoteReady = async () => /Tello Remote/.test(await page.evaluate(() => document.body.innerText || '')) && await tVisible('Take off') && await tVisible('Release');
    if (!(await poll(remoteReady, 25000, 250))) throw new Error('beat 5: Tello remote not ready within 25 s');
    await scrubSecrets(page); mark('beat5-open');
    const r5 = await reading('remote open');
    tlog(`aria-labels attached: ${(await Promise.all(['Up', 'Down', 'Rotate left', 'Rotate right', 'Move pad', 'Emergency stop'].map(async l => `${l}=${await ariaAttached(l)}`))).join(', ')}`);
    if (r5.temp === null || r5.temp >= 85) {
      takeState.status = 'FAILED_GATE'; takeState.reason = `temperature ${r5.temp ?? 'unreadable'} C`;
      console.log(`TEMP GATE ${r5.temp} C: no take off, take marked FAILED_GATE`);
      await sleep(1500); mark('gate-stop');
      await recStop(); recStop = null;
      const rel = tBtn('Release'); if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); await sleep(2500); console.log('control released'); }
      controlHeld = false; results.push({ beat: 5, verdict: 'FAILED_GATE', detail: takeState.reason });
      return;
    }
    await sleep(3000); mark('beat5-end');
    // beat 6: ONE click on Take off (airborne from the click); optional "Tap again to take off"
    await reading('before take off');
    airborne = true;
    mark('beat6-click');
    await tClick('Take off');
    if (await poll(() => tVisible('Tap again to take off'), 1500, 50)) await tClick('Tap again to take off', true);
    if (!(await poll(() => tVisible('Land'), 12000, 200))) throw new Error('beat 6: no "Land" button within 12 s after take off');
    const h6 = await poll(async () => { const v = await readHeight(); return v > 0 ? v : null; }, 10000, 300);
    if (!h6) throw new Error('beat 6: height did not rise above 0 within 10 s');
    mark('beat6-airborne'); await sleep(3000); await reading('hover'); mark('beat6-end');
    // beat 7: Rotate right x3, then 2 s hold
    mark('beat7-start');
    for (let i = 0; i < 3; i++) { await rotateClick('Rotate right'); await sleep(PAUSE_ROTATE_MS); }
    await sleep(2000); mark('beat7-end');
    // beat 8: the 2 s hold after the last right turn is the wait; Rotate left x3, hold 2 s
    mark('beat8-start');
    for (let i = 0; i < 3; i++) { await rotateClick('Rotate left'); await sleep(PAUSE_ROTATE_MS); }
    await sleep(2000); await reading('after rotations'); mark('beat8-end');
    // beat 10: Land, wait for Take off enabled and height ~0, hold 4 s, THEN Release
    mark('beat10-click');
    await tClick('Land');
    let down = await poll(async () => (await tEnabled('Take off')) && (((await readHeight()) ?? 0) <= 0.15), 15000, 300);
    if (!down && await tVisible('Land')) { await tClick('Land'); down = await poll(async () => (await tEnabled('Take off')) && (((await readHeight()) ?? 0) <= 0.15), 15000, 300); }
    if (!down) throw new Error('beat 10: not landed within 30 s (Take off not enabled / height not ~0)');
    airborne = false; mark('beat10-landed'); await reading('landed');
    await sleep(4000); mark('beat10-hold-end');
    await glideTo(tBtn('Release')); controlHeld = false; await sleep(2000); mark('beat10-end');
    if (process.env.PROMO_AI_SCENE !== '0') await aiScene();   // scene ai (telemetry only); PROMO_AI_SCENE=0 switches it off
    await recStop(); recStop = null;
    takeState.status = 'OK'; results.push({ beat: 10, verdict: 'PASS', detail: 'take complete' });
  }
  try {
  if (MODE === 'take' || MODE === 'ai') { await takeFlow(); } else {
    // beat 1: Device page, Tello tile present, Not paired
    await page.goto(url('/device-control'), { waitUntil: 'load', timeout: 180000 }); await sleep(4000);
    const sel = page.locator('.MuiFormControl-root:has(label:has-text("Server")) .MuiSelect-select').first();
    await sel.waitFor({ timeout: 30000 });
    if ((await sel.innerText()).trim() !== SERVER_LABEL) {
      await sel.click(); await sleep(800);
      await page.locator('[role="option"]').filter({ hasText: new RegExp(`^${SERVER_LABEL}`) }).first().click({ timeout: 10000 })
        .catch(() => fail(1, `no "${SERVER_LABEL}" option in the Server select`));
    }
    const label = await poll(async () => { const t = (await sel.innerText()).trim(); return t === SERVER_LABEL ? t : null; }, 60000, 1000);
    if (!label) fail(1, `Server select never showed "${SERVER_LABEL}" (last: "${(await sel.innerText()).trim()}")`);
    await sleep(9000);
    await page.mouse.move(800, 300); await sleep(15000);
    await scrubSecrets(page);
    const s1 = await poll(async () => { const s = await snapshot(); return s.tiles === 1 ? s : null; }, 60000, 1000);
    if (!s1) fail(1, `expected exactly one device tile for ${DRONE_NAME}, found ${(await snapshot()).tiles}`);
    await centerTile();
    await sleep(1000);
    const lockInfo = await page.evaluate(() => [...document.querySelectorAll('svg[data-testid*="Lock" i]')].map(s => {
      const host = s.closest('[aria-label],[title]'); return (s.getAttribute('data-testid') || '') + ' | ' +
        (host ? (host.getAttribute('aria-label') || host.getAttribute('title') || '') : '') + ' | ' + (s.closest('[role="tooltip"]') ? 'tooltip' : ''); }));
    log(1, `lock icons on the page: ${lockInfo.length ? lockInfo.join(' ; ') : 'none'}`);
    const paired = !s1.chips.some(c => /^(Scan|Rescan)$/.test(c));
    const notPaired = /Not paired/i.test(s1.tileText);
    await centerTile();
    await page.screenshot({ path: path.join(OUT, 'beat1-device.png') });
    if (paired) log(1, 'drone card shows no Scan chip: already paired (reported, continuing)');
    pass(1, `drone card present; ${notPaired ? 'state "Not paired"' : 'no "Not paired" text on the card'}; Scan chip ${paired ? 'absent (paired)' : 'present'}`);

    // beat 2: wait up to 120 s for a Scan chip inside the drone card (the drone may power on late). A card that already has a
    // loaded preview and a battery % is paired and skips Scan; otherwise Scan is clicked and "Scanning" must appear in that card.
    const tileOk = s => s.tiles === 1 && s.loaded && s.battery !== null;
    const scanChipOn = s => s.tiles === 1 && s.chips.some(c => /^(Scan|Rescan)$/.test(c));
    const beat2Start = Date.now();
    let s2 = null;
    while (Date.now() - beat2Start < 120000) {
      s2 = await snapshot().catch(() => null);
      if (s2 && (tileOk(s2) || scanChipOn(s2))) break;
      await sleep(500);
    }
    if (!s2 || s2.tiles !== 1) fail(2, `expected exactly one device tile for ${DRONE_NAME}, found ${s2 ? s2.tiles : 0}`);
    let t2 = null;
    if (tileOk(s2)) {
      pass(2, 'skipped: drone card already paired (loaded preview and battery %), no Scan needed');
    } else {
      if (!scanChipOn(s2)) fail(2, `no Scan chip inside the drone tile within 120 s (card "${s2.tileText.slice(0, 240)}")`);
      const scanChip = page.locator('[data-drone-tile="1"] .MuiChip-root').filter({ hasText: /^(Scan|Rescan)$/ });
      const nScan = await scanChip.count();
      if (nScan !== 1) fail(2, `expected exactly one Scan chip inside the drone tile, found ${nScan}`);
      log(2, `Scan chip inside the drone tile after ${((Date.now() - beat2Start) / 1000).toFixed(1)} s`);
      t2 = Date.now();
      await centerTile();
      await scanChip.click();
      const scanning = await poll(async () => { const s = await snapshot(); return s.tiles === 1 && /Scanning/i.test(s.tileText) ? s : null; }, 8000, 250);
      if (!scanning) fail(2, '"Scanning" did not appear inside the drone tile within 8 s of Scan');
      await centerTile();
      await page.screenshot({ path: path.join(OUT, 'beat2-scanning.png') });
      pass(2, `Scan chip inside the drone card clicked; "Scanning" inside that card within ${((Date.now() - t2) / 1000).toFixed(1)} s`);
    }

    // beat 3: pass only from the drone card (loaded preview <img> plus a battery % badge); every check reads that card's text only.
    // "Could not pair" / "Drone not found" are stale until the 40 s grace ends; "Drone not found" for 45 s after that stops the beat.
    const pairStart = t2 ?? Date.now();
    const GRACE_MS = 40000, LIMIT_MS = 120000, NOT_FOUND_STOP_MS = 45000;
    let s3 = null, notFoundSince = null, lastLog = -10000, srcLogged = false;
    while (Date.now() - pairStart < LIMIT_MS) {
      const elapsed = Date.now() - pairStart;
      s3 = await snapshot().catch(() => null);
      if (s3 && s3.tiles === 1 && !srcLogged) { log(3, `drone preview img src starts "${s3.src || 'no img'}"`); srcLogged = true; }
      if (s3 && tileOk(s3)) break;
      const txt = s3 ? s3.tileText : '';
      if (elapsed - lastLog >= 10000) {
        log(3, `${(elapsed / 1000).toFixed(0)} s after Scan, drone card: "${txt.slice(0, 240) || `${s3 ? s3.tiles : 0} cards matched`}"`);
        lastLog = elapsed;
      }
      if (elapsed >= GRACE_MS) {
        if (/could not pair/i.test(txt)) fail(3, `"Could not pair" on the drone card ${(elapsed / 1000).toFixed(0)} s after Scan, no tile video yet`);
        notFoundSince = /drone not found/i.test(txt) ? (notFoundSince ?? Date.now()) : null;
        if (notFoundSince && Date.now() - notFoundSince >= NOT_FOUND_STOP_MS) fail(3, '"Drone not found" on the drone card for 45 s after Scan: drone off / not found, beat stopped (no retry)');
      }
      await sleep(300);
    }
    if (!s3 || !tileOk(s3)) fail(3, `drone card had no loaded preview image and battery % within 120 s of Scan (tiles ${s3 ? s3.tiles : 0}, text "${s3 ? s3.tileText.slice(0, 240) : ''}")`);
    await scrubSecrets(page);
    await centerTile();
    await page.screenshot({ path: path.join(OUT, 'beat3-paired.png') });
    pass(3, `drone card: preview <img> loaded, badge ${s3.battery}%${s3.temp ? ' ' + s3.temp + ' °C' : ''}, ${((Date.now() - pairStart) / 1000).toFixed(1)} s after Scan`);

    // beat 4: a real mouse click at the centre of the tile preview; the REC overlay covers the preview, so element.click() is not used
    const tileImg = page.locator('[data-drone-preview="1"]').first();
    await centerTile();
    await tileImg.scrollIntoViewIfNeeded().catch(() => {});
    await sleep(800);
    const imgBox = await tileImg.boundingBox().catch(() => null);
    if (!imgBox) fail(4, 'Tello tile preview (largest media in the drone card) not clickable');
    await glide(page, imgBox.x + imgBox.width / 2, imgBox.y + imgBox.height / 2);
    // robust: no role=dialog / <video> dependency; success = visible exact "Control" button + visible "Last 24h" on the Device page
    const recState = () => page.evaluate(() => {
      const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
      const take = [...document.querySelectorAll('button')].some(b => vis(b) && b.textContent.trim() === 'Control');
      const last24 = /Last 24h/.test(document.body.innerText || '');
      return { take, last24 };
    });
    const rec = await poll(async () => {
      if (/\/monitoring\//.test(page.url())) return { navigated: true };
      const s = await recState(); return s && s.take && s.last24 && !/\/monitoring\//.test(page.url()) ? s : null;
    }, 20000, 250);
    if (rec && rec.navigated) { await page.goBack().catch(() => {}); fail(4, `BLOCKED: click navigated to ${page.url()}; went back, stopped`); }
    if (!rec) fail(4, 'REC view did not open within 20 s (no visible "Control" button + "Last 24h" on the Device page)');
    await scrubSecrets(page);
    await centerTile();
    await page.screenshot({ path: path.join(OUT, 'beat4-rec.png') });
    pass(4, 'REC view open (visible "Control" button + "Last 24h")');

    // beat 5: Take control shows the Tello remote. STOP: no flight command is sent.
    const take = page.locator('button').filter({ hasText: /^\s*Control\s*$/ }).first();
    await take.waitFor({ state: 'visible', timeout: 20000 }).catch(() => fail(5, 'no "Control" button in the REC view'));
    const tb = await take.boundingBox(); if (!tb) fail(5, '"Control" button has no box');
    await glide(page, tb.x + tb.width / 2, tb.y + tb.height / 2);
    await page.mouse.click(tb.x + tb.width / 2, tb.y + tb.height / 2); controlHeld = true;
    const logLabels = async () => { const f = []; for (const l of ['Up', 'Down', 'Rotate left', 'Rotate right', 'Move pad', 'Emergency stop']) f.push(`${l}=${await ariaAttached(l)}`); return f.join(', '); };
    const remoteState = async () => ({
      title: /Tello Remote/.test(await page.evaluate(() => document.body.innerText || '').catch(() => '')),
      take: await tVisible('Take off'),
      release: await tVisible('Release'),
    });
    if (!(await poll(async () => { const r = await remoteState(); return r.title && r.take && r.release; }, 25000, 250))) {
      const r = await remoteState(); fail(5, `Tello remote not ready within 25 s: title=${r.title}, "Take off" button=${r.take}, "Release" button=${r.release}; aria-labels: ${await logLabels()}`);
    }
    log(5, `aria-labels attached: ${await logLabels()}`);
    await scrubSecrets(page);
    const h5 = await readHeight(); const bat5 = await batteryPct();
    const temp5 = (await panelBadge()).temp;
    await page.screenshot({ path: path.join(OUT, 'beat5-remote.png') });
    pass(5, `Tello remote shown (Tello Remote title, Take off button, Release button), H ${h5 ?? 'n/a'} m, battery ${bat5 ?? 'n/a'}%, temperature ${temp5 !== null ? temp5 + ' °C' : 'n/a'}`);

    if (MODE === 'flight') {
      // take-off gate: a drone card or remote reading of 85 C or more ends the run before any flight command; control is released in finally
      const readTemp = async () => {
        const rem = (await panelBadge()).temp;
        const temps = [(await snapshot()).temp, rem].filter(v => v !== null && v !== undefined);
        return temps.length ? Math.max(...temps) : null;
      };
      const gate = await poll(async () => { const t = await readTemp(); return t === null ? null : { t }; }, 3000, 250);
      const temp6 = gate ? gate.t : null;
      if (temp6 !== null && temp6 >= 85) {
        console.log(`TEMP GATE ${temp6} C`);
        results.push({ beat: 6, verdict: 'BLOCKED', detail: `TEMP GATE ${temp6} C: no take off` });
        return;
      }
      if (temp6 === null) log(6, 'no temperature reading, take off not gated');
      // beat 6: first click arms, second click flies; height must rise above 0 within 10 s
      const bat6 = await batteryPct();
      const t6 = Date.now();
      airborne = true; // from the moment the click is sent
      await tClick('Take off');
      // second click must come within the 3 s arm window: no slow work in between
      // either path: no arm step (deployed remote), or an optional "Tap again to take off" within 1.5 s
      if (await poll(() => tVisible('Tap again to take off'), 1500, 50)) await tClick('Tap again to take off', true);
      if (!(await poll(() => tVisible('Land'), 12000, 200))) fail(6, 'no "Land" button within 12 s after take off');
      const h6 = await poll(async () => { const v = await readHeight(); return v > 0 ? v : null; }, 10000, 300);
      const guard6 = await remoteLine();
      await page.screenshot({ path: path.join(OUT, 'beat6-takeoff.png') });
      if (!h6) fail(6, `height did not rise above 0 within 10 s (H ${await readHeight()} m, remote line "${guard6}"); no further flight command`);
      pass(6, `airborne, H ${h6.toFixed(2)} m after ${((Date.now() - t6) / 1000).toFixed(1)} s, battery ${bat6}% before, remote line "${guard6 || '-'}"`);

      // beat 7: hover 5 s, sample height each second
      const samples = []; const t7 = Date.now();
      while (Date.now() - t7 < 5000) { samples.push(await readHeight()); await sleep(1000); }
      if (!(await tVisible('Land'))) fail(7, 'Land button gone during the hover (not airborne)');
      const bat7 = await batteryPct(); const guard7 = await remoteLine();
      await page.screenshot({ path: path.join(OUT, 'beat7-hover.png') });
      pass(7, `hover 5 s, H samples ${samples.join(', ')} m, battery ${bat7}%, remote line "${guard7 || '-'}"`);

      // beat 8: one Land; land within 15 s, else one more Land click, then 15 s more
      const t8 = Date.now();
      await tClick('Land');
      let down = await poll(() => tEnabled('Take off'), 15000, 300);
      if (!down && await tVisible('Land')) {
        await tClick('Land');
        down = await poll(() => tEnabled('Take off'), 15000, 300);
      }
      if (!down) fail(8, 'not landed within 30 s (Take off button not back)');
      airborne = false;
      const h8 = await readHeight(); const bat8 = await batteryPct(); const guard8 = await remoteLine();
      await page.screenshot({ path: path.join(OUT, 'beat8-landed.png') });
      pass(8, `landed in ${((Date.now() - t8) / 1000).toFixed(1)} s, H ${h8} m, battery ${bat8}% after, remote line "${guard8 || '-'}"`);
    }
  }
  } catch (e) {
    await centerTile();
    await page.screenshot({ path: path.join(OUT, 'fail.png') }).catch(() => {});
    results.push({ verdict: 'FAIL', detail: redact(e.message) });
    console.error(redact(e.stack || e.message));
  } finally {
    await page.mouse.up().catch(() => {});   // never leave a control pressed
    let landed = !airborne;
    if (airborne) {
      const TO = 'Taking off(…|\\.\\.\\.)', LG = 'Landing(…|\\.\\.\\.)';
      try {
        if (await tVisible(TO)) await poll(() => tVisible('Land'), 8000, 200);
        if (await tVisible('Land')) await tClick('Land').catch(() => {});
        landed = !!(await poll(() => tEnabled('Take off'), 20000, 300));
        if (!landed && await tVisible('Land')) { await tClick('Land').catch(() => {}); landed = !!(await poll(() => tEnabled('Take off'), 20000, 300)); }
      } catch (e2) { console.log(`safety land error: ${e2.message}`); }
      console.log(`safety land after error: ${landed ? 'landed (Take off enabled again)' : 'NOT confirmed landed, check the drone'}`);
    }
    if (controlHeld && landed) {
      const rel = page.getByRole('button', { name: /^release$/i }).first();
      if (await rel.isVisible().catch(() => false)) { await rel.click().catch(() => {}); await sleep(3000); console.log('control released'); }
      else console.log('control: no Release button visible at the end');
    } else if (controlHeld) console.log('control NOT released: landing not confirmed, drone may be airborne');
    if (recStop) { await recStop().catch(() => {}); recStop = null; }
    if (MODE === 'take' || MODE === 'ai') {
      if (takeState.status === 'RUNNING') takeState.status = 'FAILED';
      fs.writeFileSync(path.join(OUT, MODE === 'ai' ? 'drone_ai.marks.json' : 'drone.marks.json'), JSON.stringify(takeState, null, 1));
      console.log(`take status ${takeState.status}`);
    }
    await browser.close();
    console.log(JSON.stringify(results, null, 1));
    console.log(`elapsed ${((Date.now() - t0All) / 1000).toFixed(0)} s`);
  }
  if (results.some(r => r.verdict === 'FAILED_GATE')) process.exit(3);
  if (results.some(r => r.verdict === 'FAIL')) process.exit(1);
})();
