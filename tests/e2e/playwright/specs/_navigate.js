const DEFAULT_BASE_URL = 'http://localhost:5073';
const AUTO_SIGN_PARAM = 'auto_signed';

const baseUrl = (process.env.E2E_BASE_URL || DEFAULT_BASE_URL).replace(/\/$/, '');
const autoSignToken = process.env.E2E_AUTO_SIGN_TOKEN || '';
let hasLoggedAutoSign = false;

// Chrome fires `net::ERR_NETWORK_CHANGED` mid-navigation when the browser's
// network interface has just changed (LAN runner bridging a new host, VPN
// reconnect, browser started before the link was up). It is the single
// transient we see repeatedly on the shared CI runners — the surrounding
// page fetch is fine 200-300 ms later. The same class covers the rare
// `net::ERR_INTERNET_DISCONNECTED` / `net::ERR_CONNECTION_RESET`. Catching
// only these means the retry is a no-op for genuine 4xx/5xx, assertion
// failures, or auth-gone-401: those surface to the caller unchanged.
const TRANSIENT_NETWORK_ERRORS = Object.freeze([
  'net::ERR_NETWORK_CHANGED',
  'net::ERR_INTERNET_DISCONNECTED',
  'net::ERR_CONNECTION_RESET',
]);
const GOTO_TRANSIENT_RETRIES = 2;
const GOTO_TRANSIENT_DELAY_MS = 1500;

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

function _isTransientNetworkError(err) {
  const msg = String((err && err.message) || err || '');
  return TRANSIENT_NETWORK_ERRORS.some((needle) => msg.includes(needle));
}

async function gotoWithAutoSign(page, path, options = {}) {
  const url = withAutoSign(buildUrl(path));
  if (autoSignToken && !hasLoggedAutoSign) {
    // Never print the token: this stdout lands in the published Playwright report.
    console.log(`🔐 Auto-sign navigation enabled: ${url.replace(/(auto_signed=)[^&]+/, '$1***')}`);
    hasLoggedAutoSign = true;
  }
  let lastError;
  for (let attempt = 0; attempt <= GOTO_TRANSIENT_RETRIES; attempt++) {
    try {
      return await page.goto(url, options);
    } catch (err) {
      lastError = err;
      const transient = _isTransientNetworkError(err);
      if (!transient || attempt === GOTO_TRANSIENT_RETRIES) {
        throw err;
      }
      console.warn(
        `🔄 gotoWithAutoSign: transient network error on ${path} ` +
        `(attempt ${attempt + 1}/${GOTO_TRANSIENT_RETRIES + 1}, retry in ${GOTO_TRANSIENT_DELAY_MS}ms): ` +
        String((err && err.message) || err).split('\n')[0],
      );
      await page.waitForTimeout(GOTO_TRANSIENT_DELAY_MS);
    }
  }
  // Unreachable: the loop above either returns or throws. Defensive throw to
  // keep TypeScript happy and silence the "possibly undefined" lint.
  throw lastError;
}

module.exports = {
  gotoWithAutoSign,
};
