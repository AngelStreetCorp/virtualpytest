// Shared by the captures: API calls with the auto-sign token, the CORS relay for a local Vite on rpitest,
// the secret/IP scrub before anything is filmed, the host-session cookie mint, the CDP screencast recorder
// (true 1920x1080) and the fake-cursor glide. A capture calls lib(<raw dir>) once. A guard that a second
// capture needs goes here, never into a copy (promo_check.py is the sensor that catches what slips through).
const fs = require('fs'); const path = require('path'); const https = require('https');
const DIR = __dirname;
const TOKEN = fs.readFileSync(path.join(DIR, '.token'), 'utf8').trim();
const TEAM = '7fdeb4bb-3639-4ec3-959f-b54769a219ce';
const SERVER = process.env.PROMO_SERVER || (/^https:\/\/virtualpytest\.angelstreet\.io/.test(process.env.PROMO_BASE || '') ? process.env.PROMO_BASE : null); if (!SERVER) throw new Error('PROMO_SERVER is required (public URL of the server, e.g. https://<server>.angelstreet.io)'); const BASE = process.env.PROMO_BASE || 'https://localhost:5074';
const VIEW = { width: 1920, height: 1080 };
const url = (p) => `${BASE}${p}${p.includes('?') ? '&' : '?'}auto_signed=${TOKEN}`;
const CURSOR = fs.readFileSync(path.join(DIR, 'capture.js'), 'utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];
const redact = (s) => String(s).replaceAll(TOKEN, '<token>');

module.exports = (OUT, { viewCss = { width: 1280, height: 720 } } = {}) => {
  function api(method, p, body) {
    return new Promise((resolve, reject) => {
      const u = new URL(`${SERVER}${p}`); u.searchParams.set('team_id', TEAM);
      const data = body ? JSON.stringify(body) : null;
      const headers = { 'User-Agent': 'Mozilla/5.0', 'X-Auto-Sign': TOKEN };
      if (data) { headers['Content-Type'] = 'application/json'; headers['Content-Length'] = Buffer.byteLength(data); }
      const req = https.request(u, { method, headers }, res => { let s = ''; res.on('data', d => s += d); res.on('end', () => { try { resolve(JSON.parse(s)); } catch (e) { resolve({ raw: s.slice(0, 200) }); } }); });
      req.on('error', reject); if (data) req.write(data); req.end();
    });
  }
  // base: the local frontend origin the CORS headers name (default PROMO_BASE)
  async function relay(ctx, { base = BASE } = {}) {
    // node screenshots and other stored images come from the storage proxy on the main site with
    // Cross-Origin-Resource-Policy: same-origin, which blocks them on the local origin: serve them without that header
    await ctx.route(/^https:\/\/virtualpytest\.angelstreet\.io\/virtualpytest\//, async route => {
      try { const r = await route.fetch({ timeout: 60000 }); const h = { ...r.headers() }; delete h['cross-origin-resource-policy']; delete h['cross-origin-embedder-policy'];
        await route.fulfill({ response: r, headers: h }); } catch (e) { await route.abort().catch(() => {}); }
    });
    if (new URL(SERVER).origin !== new URL(BASE).origin) await ctx.route(new RegExp('^' + SERVER.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '/'), async route => {
      const req = route.request(); const cors = { 'access-control-allow-origin': base, 'access-control-allow-credentials': 'true', 'vary': 'Origin' };
      if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { ...cors, 'access-control-allow-methods': 'GET,POST,PUT,DELETE,PATCH,OPTIONS', 'access-control-allow-headers': req.headers()['access-control-request-headers'] || '*' } });
      // archive chunks are tens of MB and <video> asks for open ranges (bytes=N-). Through route.fetch they stall the
      // relay: Playwright queues every relayed request behind them, the page's API calls time out at 30 s and it shows
      // "Failed to fetch". So media goes through Node's own https client, 2 MB per range; the element asks for the next.
      if (req.resourceType() === 'media') {
        const h = { ...req.headers() }; const rg = /^bytes=(\d+)-(\d*)$/.exec(h['range'] || 'bytes=0-');
        h['range'] = `bytes=${rg[1]}-${rg[2] || Number(rg[1]) + 2 * 1024 * 1024 - 1}`; delete h['host'];
        try {
          const r = await new Promise((resolve, reject) => {
            const q = https.request(req.url(), { method: 'GET', headers: h, timeout: 60000 }, res => {
              const chunks = []; res.on('data', c => chunks.push(c)); res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
            });
            q.on('timeout', () => q.destroy(new Error('media timeout'))); q.on('error', reject); q.end();
          });
          const rh = {}; for (const [k, v] of Object.entries(r.headers)) if (k !== 'access-control-allow-origin') rh[k] = Array.isArray(v) ? v.join(', ') : String(v);
          return route.fulfill({ status: r.status, headers: { ...rh, ...cors }, body: r.body });
        } catch (e) { if (process.env.RELAY_DEBUG) console.log('RELAYERR media', e.message.slice(0, 120)); return route.abort().catch(() => {}); }
      }
      const opts = { timeout: 600000 };   // AI generation/validation calls take 30-50 s and a Test Prompt explore run ~4 min (the execute call stays open); the 30 s default showed "Failed to fetch"
      try { const r = await route.fetch(opts); const h = { ...r.headers() }; delete h['access-control-allow-origin']; await route.fulfill({ response: r, headers: { ...h, ...cors } }); }
      catch (e) { if (process.env.RELAY_DEBUG) console.log('RELAYERR', e.message.slice(0, 200), req.url().slice(0, 90)); await route.abort().catch(() => {}); }
    });
  }
  // Playwright's recordVideo captures CSS pixels, so a 1280x720 page at 1.5x comes out 1280x720. This records
  // the CDP screencast (device pixels, 1920x1080) to JPEG frames and joins them by their timestamps.
  const VIEW_CSS = viewCss, DPR = VIEW.width / viewCss.width;   // CSS page size scaled to a 1920x1080 recording
  async function startRecorder(page, name) {
    const dir = path.join(OUT, `frames-${name}`); fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir);
    const cdp = await page.context().newCDPSession(page); const frames = [];
    cdp.on('Page.screencastFrame', async f => { const file = path.join(dir, `${String(frames.length).padStart(6, '0')}.jpg`);
      fs.writeFileSync(file, Buffer.from(f.data, 'base64')); frames.push({ file, t: f.metadata.timestamp }); cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {}); });
    const start = async () => cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: VIEW.width, maxHeight: VIEW.height, everyNthFrame: 1 });
    await start(); page.on('framenavigated', f => { if (f === page.mainFrame()) start().catch(() => {}); });
    const t0 = Date.now() / 1000;
    return async () => {
      await cdp.send('Page.stopScreencast').catch(() => {});
      // concat list: each frame lasts until the next one; the first starts at t0 (marks are relative to t0)
      const lines = []; let prev = t0;
      for (let i = 0; i < frames.length; i++) { const next = i + 1 < frames.length ? frames[i + 1].t : frames[i].t + 0.5;
        if (i === 0) prev = Math.min(prev, frames[0].t); lines.push(`file '${frames[i].file}'`, `duration ${Math.max(0.001, (i === 0 ? next - t0 : next - frames[i].t)).toFixed(3)}`); }
      if (frames.length) lines.push(`file '${frames[frames.length - 1].file}'`);
      const list = path.join(dir, 'list.txt'); fs.writeFileSync(list, lines.join('\n'));
      const out = path.join(OUT, `${name}.mp4`);
      // frames come at two sizes (1x and DPR): frames_to_mp4.py resizes them to one size before joining, or the page flashes
      require('child_process').execFileSync('python3', [path.join(DIR, 'frames_to_mp4.py'), dir, out, String(VIEW.width), String(VIEW.height)], { stdio: 'inherit' });
      console.log(`recorded ${name}.mp4 (${frames.length} frames)`);
    };
  }
  // Reports print the caller's public IP ("ip=<addr>", or "ip <strong>addr</strong>" in the Trigger line) and logs
  // print the device environment (cloud-farm keys, users). Each value is swapped for a placeholder (•••) drawn
  // blurred, so the take shows a blur where the value was and the real value never reaches the page's pixels.
  // Text rendered later is handled too (MutationObserver); throws if a value is still readable.
  // Call it after every navigation, before the page is filmed.
  async function scrubSecrets(page) {
    const left = await page.evaluate(() => {
      const IP = '\\b\\d{1,3}(?:\\.\\d{1,3}){3}\\b';
      const blurred = (txt) => { const b = document.createElement('span'); b.dataset.promoBlur = '1';
        b.style.cssText = 'filter:blur(5px);-webkit-filter:blur(5px);user-select:none'; b.textContent = txt; return b; };
      // [regex, kept prefix group or null]: the value after the prefix becomes a blurred placeholder
      const RULES = [[/(\b[A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASS(?:WORD)?|USER|APP)\b\s*[=:]\s*)([^\s•]\S*)/g, '••••••••'],
        [new RegExp(`()(${IP})`, 'g'), '•••.•••.••.•••']];
      const scrubNode = (n) => {
        if (n.parentElement && n.parentElement.closest('[data-promo-blur]')) return;
        const t = n.nodeValue; const parts = []; let last = 0, hit = false;
        const all = [];
        for (const [re, ph] of RULES) { re.lastIndex = 0; let m; while ((m = re.exec(t))) all.push({ s: m.index + m[1].length, e: m.index + m[0].length, ph }); }
        all.sort((a, b) => a.s - b.s);
        for (const h of all) { if (h.s < last) continue; parts.push(document.createTextNode(t.slice(last, h.s)), blurred(h.ph)); last = h.e; hit = true; }
        if (!hit) return;
        parts.push(document.createTextNode(t.slice(last))); n.replaceWith(...parts);
      };
      const scrub = root => {
        if (root.nodeType === 3) return scrubNode(root);
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); const nodes = []; let n;
        while ((n = walker.nextNode())) nodes.push(n);
        nodes.forEach(scrubNode);
      };
      scrub(document.body);
      if (!window.__promoScrub) { window.__promoScrub = new MutationObserver(ms => { for (const m of ms) for (const a of (m.type === 'characterData' ? [m.target] : m.addedNodes)) if (a.isConnected) scrub(a); });
        window.__promoScrub.observe(document.body, { childList: true, subtree: true, characterData: true }); }
      return new RegExp(`FARM_KEY=(?!•)|\\bip\\s*=\\s*\\d|${IP}`, 'i').test(document.body.innerText);
    });
    if (left) throw new Error('a secret or IP is still on the page');
  }
  // A host-served page (comparison report, stream) needs the host-session cookie a browser gets once it has shown
  // the device: mint it the way the frontend does. The page must already be on the app's origin (base).
  async function mintHostSession(page, host, base = BASE) {
    const r = await page.request.post(`${base}/server/host-session/session?auto_signed=${TOKEN}`, { data: { host_name: host }, headers: { 'X-Auto-Sign': TOKEN } });
    console.log('host session', host, r.status()); return r.ok();
  }
  async function glide(page, x, y, pause = 500) { await page.mouse.move(x, y, { steps: 28 }); await page.waitForTimeout(pause); await page.mouse.click(x, y); }
  return { TOKEN, TEAM, SERVER, BASE, VIEW, VIEW_CSS, DPR, url, CURSOR, redact, api, relay, scrubSecrets, mintHostSession, startRecorder, glide };
};
