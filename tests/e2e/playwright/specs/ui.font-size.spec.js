// TASK-100 G7/G8: the Size picker (S / M / L = -2 / 0 / +2 px on the 16 px root) must move the text on
// every page. Loads key pages at S and L and asserts that the body text and a button differ by ~4 px,
// and that (almost) no text element keeps the same px size across the two.
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('./_navigate');

const SIZE_KEY = 'virtualpytest:theme:size';
const PAGES = ['/', '/run/tests', '/configuration/settings', '/status', '/monitoring/analytics'];

// Computed font size of every visible text element, keyed by tag + text, so S and L can be compared.
const sample = () => {
  const out = {};
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const el = w.currentNode.parentElement;
    const txt = w.currentNode.textContent.trim();
    if (!el || !txt || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || getComputedStyle(el).visibility === 'hidden') continue;
    const k = `${el.tagName}|${txt.slice(0, 40)}`;
    if (!(k in out)) out[k] = parseFloat(getComputedStyle(el).fontSize);
  }
  return { root: parseFloat(getComputedStyle(document.documentElement).fontSize), items: out };
};

async function sizeRun(browser, path, size) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, ignoreHTTPSErrors: true });
  await ctx.addInitScript(([k, v]) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage blocked */ } }, [SIZE_KEY, size]);
  const page = await ctx.newPage();
  await gotoWithAutoSign(page, path);
  if (/\/login/.test(page.url())) { await ctx.close(); return null; }
  await page.waitForTimeout(4000);
  const res = await page.evaluate(sample);
  await ctx.close();
  return res;
}

test.describe('Size picker moves the text (S vs L)', () => {
  for (const path of PAGES) {
    test(`${path}: body text differs by 4 px, no fixed-px text`, async ({ browser }) => {
      const sm = await sizeRun(browser, path, 'sm');
      const lg = await sizeRun(browser, path, 'lg');
      test.skip(!sm || !lg, 'Not authenticated - redirected to login');
      expect(sm.root).toBe(14);
      expect(lg.root).toBe(18);
      const common = Object.keys(sm.items).filter((k) => k in lg.items);
      expect(common.length).toBeGreaterThan(5);
      // The 14 px body text of the app (the most common size at S is 13 px * 14/16): L - S must be ~ 4 * (px/16).
      const frozen = common.filter((k) => sm.items[k] === lg.items[k]);
      expect(frozen.slice(0, 10), `text that did not follow the Size picker on ${path}`).toEqual([]);
      const deltas = common.map((k) => lg.items[k] - sm.items[k]);
      const median = deltas.sort((a, b) => a - b)[Math.floor(deltas.length / 2)];
      expect(median).toBeGreaterThan(2.5);
      expect(median).toBeLessThan(5);
    });
  }
});
