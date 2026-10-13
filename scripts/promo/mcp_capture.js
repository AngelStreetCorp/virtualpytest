// Assets for video 19 (Claude Code drives VirtualPyTest over MCP). ONE recorded page, 1600x900 CSS:
// LEFT 58% the VirtualPyTest device modal of host-clone-1 (stream enlarged: black monitoring player above the VNC frame hidden), RIGHT 42% a ttyd web terminal running Claude Code
// with the VPT MCP server. The main site sends X-Frame-Options: SAMEORIGIN, so the wrapper page (mcp_wrapper.html)
// is served by a Playwright route AT the site's own origin (/__mcp19.html): the left iframe is then same-origin and
// may load the site; the right iframe is ttyd on https://127.0.0.1:7681 (self-signed, no frame header; plain http is blocked as mixed content).
// The key never shows: it is read from a 0600 file into the demo shell's env (VPT_MCP_KEY), ~/mcp-demo/.mcp.json
// holds "Bearer ${VPT_MCP_KEY}". Setup: ~/bin/mcp-ttyd-start.sh (ttyd, fontSize 18, dark, PS1='$ ', cwd ~/mcp-demo).
// Lease host-clone-1 BEFORE running (vpt-lease claim node1-vpt host-clone-1 ...) and release after.
// Usage: node mcp_capture.js scout   -> raw19/scout-*.png + scout.log (stills every few s, answers, tools, durations)
//        node mcp_capture.js         -> raw19/mcp.mp4 + mcp.marks.json   (final take: not run yet)
// MCP_PROMPTS='a|b|c' overrides the prompt list (| separated).
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const DIR = __dirname; const OUT = path.join(DIR, 'raw19'); fs.mkdirSync(OUT, { recursive: true });
const { VIEW_CSS, DPR, BASE, TOKEN, url, CURSOR, redact, relay, startRecorder, glide } = require('./promo_lib')(OUT, { viewCss: { width: 1600, height: 900 } });
const ORIGIN = new URL(BASE).origin; const PAGE = `${ORIGIN}/__mcp19.html`;
const PROMPTS = (process.env.MCP_PROMPTS ? process.env.MCP_PROMPTS.split('|') : [
  'Which VirtualPyTest devices can you use?',
  'On host-clone-1, use the youtube-web interface to open the search results page',
  'Now go to the home page',
  "What's on the screen now?",
  'Verify that we are on the home node',
]);

async function newContext(browser) {
  const ctx = await browser.newContext({ viewport: VIEW_CSS, deviceScaleFactor: DPR, ignoreHTTPSErrors: true });
  await ctx.addInitScript(CURSOR);
  await relay(ctx);
  const html = fs.readFileSync(path.join(DIR, 'mcp_wrapper.html'), 'utf8').replace('__VPT_SRC__', url('/device-control'));
  await ctx.route(PAGE, r => r.fulfill({ status: 200, contentType: 'text/html', body: html }));
  return ctx;
}
const termText = f => f.evaluate(() => (document.querySelector('.xterm-rows') || document.body).innerText);
const redactMail = s => s.replace(/[\w.+-]+@[\w.-]+\.\w+/g, '<email>');

async function walk(page, mark, shot, log) {
  // the token must be in sessionStorage of the origin before the iframe's probe: load / once, then the wrapper
  await page.goto(url('/'), { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2000);
  await page.goto(PAGE, { waitUntil: 'load', timeout: 180000 });
  let left, term;
  for (let i = 0; i < 60 && !(left && term); i++) { await page.waitForTimeout(500);
    left = page.frames().find(f => /\/device-control/.test(f.url())); term = page.frames().find(f => f.url().startsWith('https://127.0.0.1:7681')); }
  if (!left || !term) throw new Error('frames missing: ' + page.frames().map(f => f.url().replace(TOKEN, '<t>')).join(' '));
  // open the host-clone-1 modal, HD
  const title = left.locator('text=/^host-clone-1$/').first(); await title.waitFor({ timeout: 90000 }); await page.waitForTimeout(3000);
  const tb = await title.boundingBox(); await glide(page, tb.x + 120 * 0.928, tb.y + tb.height + 80 * 0.928, 700);
  const hd = left.locator('button[aria-label="High definition"]').first();
  if (await hd.isVisible({ timeout: 10000 }).catch(() => false)) { await page.waitForTimeout(1500); const b = await hd.boundingBox(); await glide(page, b.x + b.width / 2, b.y + b.height / 2, 600); } else log('no HD button');
  // enlarge the stream: hide the (black) monitoring player above the VNC frame and let the frame take the freed height
  const enlarge = () => left.evaluate(() => { const f = document.querySelector('iframe[src*="vnc"]'); if (!f) return; const prev = f.previousElementSibling; if (prev) prev.style.display = 'none'; }).catch(() => {});
  await enlarge();
  await page.mouse.move(1000, 800, { steps: 15 }); mark('modal'); await shot('modal');
  // terminal: start Claude Code
  const tx = 928 + 336, ty = 450; await page.mouse.click(tx, ty); await page.waitForTimeout(800);
  for (let i = 0; i < 40; i++) { await enlarge(); await page.waitForTimeout(500); }   // the VNC frame appears 20-40 s after the modal opens
  await page.keyboard.type('claude', { delay: 90 }); await page.keyboard.press('Enter'); mark('claude-start');
  for (let i = 0; i < 30; i++) { await page.waitForTimeout(1000); if (/\? for shortcuts|bypass|>\s*$/m.test(await termText(term))) break; }
  await page.waitForTimeout(2500); mark('claude-ready'); await shot('claude-ready');
  log('--- welcome screen text ---\n' + redactMail(await termText(term)).trim().slice(0, 1500));
  const full = await termText(term); if (/@/.test(full)) log('!! an @ sign is on the terminal (email/account?)');
  for (let n = 0; n < PROMPTS.length; n++) {
    const p = PROMPTS[n]; const t0 = Date.now(); const N = n + 1; const zone = { x: 46, y: 330, width: 620, height: 300 }; const before = (await page.screenshot({ clip: zone })).toString('base64'); let moved = false;
    await page.keyboard.type(p, { delay: 45 }); mark(`typed-${N}`); await page.waitForTimeout(500); await page.keyboard.press('Enter'); mark(`sent-${N}`);
    let quiet = 0, k = 0, last = ''; const seen = new Set();
    while ((Date.now() - t0) / 1000 < 240) {
      await page.waitForTimeout(1500); await enlarge(); last = await termText(term);
      if (++k % 3 === 0) await shot(`p${n + 1}-${String(k).padStart(3, '0')}`);
      if (!moved && (await page.screenshot({ clip: zone })).toString('base64') !== before) { moved = true; mark(`device-moved-${N}`); }
      for (const m of last.matchAll(/virtualpytest\s*[-:–]\s*([a-z_]+)/gi)) seen.add(m[1]);
      if (!/esc to interrupt|^\S\s+\S+…/mi.test(last.split('\n').slice(-14).join('\n')) && !/\bSent\b|Cooking|…\s*\(/.test(last.split('\n').slice(-6).join('\n'))) quiet++; else quiet = 0;
      if (quiet >= 3 && Date.now() - t0 > 4000 && /done \d+:\d+ [AP]M/.test(last.split('\n').slice(-12).join('\n')) && !/^\S\s+\S+…/m.test(last.split('\n').slice(-12).join('\n'))) break;
    }
    const dur = (Date.now() - t0) / 1000; mark(`answered-${N}`); await shot(`answered-${N}`);
    const tools = [...seen];
    log(`\n=== P${n + 1} "${p}" ${dur.toFixed(0)}s tools=[${tools.join(', ')}] ===\n` + redactMail(last).trim().split('\n').slice(-25).join('\n'));
  }
  mark('end');
}

(async () => {
  const scout = process.argv[2] === 'scout';
  const browser = await chromium.launch({ headless: true, args: ['--disable-features=LocalNetworkAccessChecks,PrivateNetworkAccessSendPreflights,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessForNavigations'] }); const ctx = await newContext(browser); const page = await ctx.newPage();
  const stop = scout ? null : await startRecorder(page, 'mcp');
  const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  const shot = name => page.screenshot({ path: path.join(OUT, `${scout ? 'scout' : 'take'}-${name}.png`) });
  const logf = path.join(OUT, scout ? 'scout.log' : 'take.log'); fs.writeFileSync(logf, '');
  const log = s => { s = redact(s); fs.appendFileSync(logf, s + '\n'); console.log(s); };
  try { await walk(page, mark, shot, log); }
  catch (e) { log('ERROR ' + e.message.slice(0, 300)); await shot('error').catch(() => {}); }
  if (!scout) fs.writeFileSync(path.join(OUT, 'mcp.marks.json'), JSON.stringify({ marks }, null, 1));   // before the (slow) encode
  if (stop) await stop();
  await ctx.close(); await browser.close();
  log((scout ? 'scout ' : 'clip mcp ') + marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
