// Record the AI agent on prod: four prompts in one chat, device panel open beside the transcript.
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const DIR = __dirname; const OUT = path.join(DIR, 'raw2'); fs.mkdirSync(OUT, { recursive: true });
const TOKEN = fs.readFileSync(path.join(DIR, '.token'), 'utf8').trim();
const B = 'https://virtualpytest.angelstreet.io';
const VIEW = { width: 1920, height: 1080 };
const CURSOR = fs.readFileSync(path.join(DIR, 'capture.js'), 'utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];
const PROMPTS = [
  ['status', 'Show device status'],
  ['script', 'Run the goto script on host-clone-1 to reach video_player on youtube-web and give me the report link.'],
  ['act', 'Open YouTube in the browser, search for "Raspberry Pi" and tell me the title of the first result.'],
  ['docs', 'What does the freeze detector consider a freeze, and where do I change its threshold?'],
];
const https = require('https');
const lockedHost = () => new Promise(res => { https.get(`${B}/server/control/lockedDevices?auto_signed=${TOKEN}&team_id=7fdeb4bb-3639-4ec3-959f-b54769a219ce`, r => { let d=''; r.on('data',c=>d+=c); r.on('end',()=>{ try { const j=JSON.parse(d); res(Object.keys(j.locked_devices||{}).some(k=>/host-clone-1/.test(k))); } catch(e){ res(false); } }); }).on('error',()=>res(false)); });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW, recordVideo: { dir: path.join(OUT, 'video-agent2'), size: VIEW } });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage(); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  const glide = async (x, y, pause = 450) => { await page.mouse.move(x, y, { steps: 26 }); await page.waitForTimeout(pause); await page.mouse.click(x, y); };
  await page.goto(`${B}/?auto_signed=${TOKEN}`, { waitUntil: 'load', timeout: 60000 }); await page.waitForTimeout(2500);
  await page.goto(`${B}/ai-agent?auto_signed=${TOKEN}`, { waitUntil: 'load', timeout: 60000 }); await page.mouse.move(960, 700); await page.waitForTimeout(8000); mark('loaded');
  // interface -> youtube-web
  const isel = page.locator('.MuiFormControl-root:has(label:has-text("Interface")) .MuiSelect-select').first();
  if (await isel.count()) { const b = await isel.boundingBox(); await glide(b.x + b.width / 2, b.y + b.height / 2); await page.waitForTimeout(900);
    const o = page.locator('[role="option"]').filter({ hasText: /^youtube-web$/ }).first(); if (await o.count()) { const ob = await o.boundingBox(); await glide(ob.x + ob.width / 2, ob.y + ob.height / 2, 300); } else await page.keyboard.press('Escape'); await page.waitForTimeout(1000); }
  // device panel
  const dp = page.locator('button[aria-label="Show device panel"]').first(); if (await dp.count()) { const b = await dp.boundingBox(); await glide(b.x + b.width / 2, b.y + b.height / 2); }
  mark('panel'); await page.waitForTimeout(65000); mark('stream'); // VNC takes ~60 s to show
  const transcript = async () => (await page.locator('main, body').first().innerText()).replace(/\s+/g, ' ');
  let first = true;
  for (const [key, text] of PROMPTS) {
    if (!first) { const nc = page.getByRole('button', { name: /new chat/i }).first(); const nb = await nc.boundingBox(); await glide(nb.x + nb.width / 2, nb.y + nb.height / 2); await page.waitForTimeout(2500); }
    first = false;
    // keep the device panel visible in the new chat
    const sp = page.locator('button[aria-label="Show device panel"]').first(); if (await sp.count()) { const b = await sp.boundingBox(); await glide(b.x + b.width / 2, b.y + b.height / 2, 300); await page.waitForTimeout(6000); }
    if (key === 'script' || key === 'act') { for (let i = 0; i < 36; i++) { if (!(await lockedHost())) break; await page.waitForTimeout(5000); } }
    const box = page.getByPlaceholder(/How can I help you|Message/).first(); const bb = await box.boundingBox();
    await glide(bb.x + 200, bb.y + bb.height / 2); await page.keyboard.type(text, { delay: 26 }); await page.waitForTimeout(600); await page.keyboard.press('Enter'); mark(`${key}-sent`);
    let last = await transcript(), stableSince = Date.now(); const ts = Date.now(); let grown = false;
    while (Date.now() - ts < 360000) {
      await page.waitForTimeout(4000);
      const cur = await transcript(); const stopBtn = await page.locator('button:has(svg[data-testid="StopIcon"]), button:has(svg[data-testid="StopCircleIcon"])').count();
      if (cur !== last) { if (!grown && cur.length > last.length + 40) { grown = true; mark(`${key}-first`); } last = cur; stableSince = Date.now(); }
      else if (grown && stopBtn === 0 && Date.now() - stableSince > 6000) break;
      else if (grown && Date.now() - stableSince > 30000) break;
    }
    mark(`${key}-answer`); await page.waitForTimeout(2500); await page.screenshot({ path: path.join(OUT, `agent2-${key}.png`) });
    fs.writeFileSync(path.join(OUT, `agent2-${key}.txt`), last.slice(-2500));
    await page.waitForTimeout(2000);
  }
  await page.mouse.move(1100, 600, { steps: 30 }); await page.waitForTimeout(3000); mark('end');
  const vid = page.video(); await ctx.close(); fs.copyFileSync(await vid.path(), path.join(OUT, 'agent2.webm'));
  fs.writeFileSync(path.join(OUT, 'agent2.marks.json'), JSON.stringify({ marks }, null, 1)); await browser.close();
  console.log('agent2 clip', marks.map(m => `${m.label}@${m.t.toFixed(0)}`).join(' '));
})();
