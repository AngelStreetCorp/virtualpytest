const DEFAULT_BASE_URL = 'http://localhost:5073';
const AUTO_SIGN_PARAM = 'auto_signed';

const baseUrl = (process.env.E2E_BASE_URL || DEFAULT_BASE_URL).replace(/\/$/, '');
const autoSignToken = process.env.E2E_AUTO_SIGN_TOKEN || '';
let hasLoggedAutoSign = false;

function buildUrl(path) {
  if (!path) return baseUrl;
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith('/')) return `${baseUrl}${path}`;
  return `${baseUrl}/${path}`;
}

function withAutoSign(url) {
  if (!autoSignToken) return url;
  const next = new URL(url);
  next.searchParams.set(AUTO_SIGN_PARAM, autoSignToken);
  return next.toString();
}

async function gotoWithAutoSign(page, path, options = {}) {
  const url = withAutoSign(buildUrl(path));
  if (autoSignToken && !hasLoggedAutoSign) {
    // Never print the token: this stdout lands in the published Playwright report.
    console.log(`🔐 Auto-sign navigation enabled: ${url.replace(/(auto_signed=)[^&]+/, '$1***')}`);
    hasLoggedAutoSign = true;
  }
  return page.goto(url, options);
}

module.exports = {
  gotoWithAutoSign,
};
