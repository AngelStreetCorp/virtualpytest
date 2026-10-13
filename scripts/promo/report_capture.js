// Record a slow walk down one report page (test report, KPI or zap report...), for a video beat that
// opens a report a chat or a step linked to. Opens a signed R2/storage URL, so no session is needed.
// Usage: node report_capture.js <report url> <name> [out dir, default raw2]   -> <out>/<name>.webm + .marks.json
const { chromium } = require(require('path').join(__dirname, '../../tests/e2e/playwright/node_modules/playwright-core'));
const fs = require('fs'); const path = require('path');
const DIR = __dirname; const [reportUrl, name, outDir = 'raw2'] = process.argv.slice(2);
const OUT = path.join(DIR, outDir); fs.mkdirSync(OUT, { recursive: true });
const VIEW = { width: 1920, height: 1080 };
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
const CURSOR = fs.readFileSync(path.join(DIR, 'capture.js'), 'utf8').match(/const CURSOR_SCRIPT = `([\s\S]*?)`;/)[1];

(async () => {
  if (!reportUrl || !name) { console.log('usage: node report_capture.js <url> <name> [out dir]'); return; }
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: VIEW, userAgent: UA, recordVideo: { dir: path.join(OUT, 'video-' + name), size: VIEW } });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage(); const marks = []; const t0 = Date.now(); const mark = l => marks.push({ label: l, t: (Date.now() - t0) / 1000 });
  try {
    await page.goto(reportUrl, { waitUntil: 'load', timeout: 120000 }); await page.mouse.move(1500, 300);
    await page.waitForFunction(() => [...document.images].every(i => i.complete && i.naturalWidth > 0), null, { timeout: 60000 }).catch(() => console.log('some images did not load'));
    await page.waitForTimeout(3000); mark('report');
    await page.screenshot({ path: path.join(OUT, name + '-top.png') });
    // slow scroll to the bottom, a pause every screen
    const total = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
    for (let y = 0; y < total; y += 120) { await page.mouse.wheel(0, 120); await page.waitForTimeout(y % 720 === 600 ? 1200 : 180); }
    await page.waitForTimeout(2500); mark('bottom');
    await page.screenshot({ path: path.join(OUT, name + '-bottom.png') });
    await page.screenshot({ path: path.join(OUT, name + '-full.png'), fullPage: true });
    mark('end');
  } catch (e) { console.log('ERROR', e.message.slice(0, 200)); }
  const vid = page.video(); await ctx.close(); fs.copyFileSync(await vid.path(), path.join(OUT, name + '.webm'));
  fs.writeFileSync(path.join(OUT, name + '.marks.json'), JSON.stringify({ marks, report_url: reportUrl.split('?')[0] }, null, 1)); await browser.close();
  console.log('clip', name, marks.map(m => `${m.label}@${m.t.toFixed(1)}`).join(' '));
})();
