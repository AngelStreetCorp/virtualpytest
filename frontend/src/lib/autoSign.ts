const AUTO_SIGN_FLAG_KEY = 'vpt_auto_signed';
// Token supplied at runtime via ?auto_signed=<token> (CI). Stored so it — not a
// token baked into the public bundle — is what gets sent to the backend.
const AUTO_SIGN_TOKEN_KEY = 'vpt_auto_sign_token';
// Hosts outside the internal LAN allowed to *silently* auto-activate (no token
// in the URL). This MUST stay empty for any public/internet host: a public host
// here means every visitor is signed in without presenting a token. Public prod
// (virtualpytest.angelstreet.io) was removed for exactly that reason — humans
// there log in normally; CI still auto-signs by passing ?auto_signed=<token>.
const TRUSTED_AUTO_SIGN_HOSTS = new Set<string>([]);
// Any host on the internal 192.168.0.0/24 LAN (proxmox VMs) is trusted too.
// Exact IPv4 match only — a naive prefix check would also match a DNS name
// like "192.168.0.5.attacker.com".
const TRUSTED_LAN_REGEX = /^192\.168\.0\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;

// Check both build-time (VITE_*) and runtime (E2E_) environment variables
const getAutoSignEnabled = () => {
  // First check build-time env var
  const buildTimeEnabled = (import.meta as any).env?.VITE_AUTO_SIGN_ENABLED || '';
  if (buildTimeEnabled) return buildTimeEnabled;
  // Fall back to runtime env var (set by CI)
  return (import.meta as any).env?.E2E_AUTO_SIGN_ENABLED || '';
};
const getAutoSignToken = () => {
  // First check build-time env var
  const buildTimeToken = (import.meta as any).env?.VITE_AUTO_SIGN_TOKEN || '';
  if (buildTimeToken) return buildTimeToken;
  // Fall back to runtime env var (set by CI)
  return (import.meta as any).env?.E2E_AUTO_SIGN_TOKEN || '';
};

const isTruthy = (value: string) =>
  value.trim().toLowerCase() in { '1': true, 'true': true, 'yes': true, 'on': true, 'enabled': true };

export const isAutoSignEnabled = (): boolean => isTruthy(getAutoSignEnabled());
export const getAutoSignTokenValue = (): string => getAutoSignToken();

export const clearAutoSignSession = () => {
  sessionStorage.removeItem(AUTO_SIGN_FLAG_KEY);
  localStorage.removeItem(AUTO_SIGN_FLAG_KEY);
  sessionStorage.removeItem(AUTO_SIGN_TOKEN_KEY);
  localStorage.removeItem(AUTO_SIGN_TOKEN_KEY);
};

const setAutoSignedSession = (token?: string | null) => {
  sessionStorage.setItem(AUTO_SIGN_FLAG_KEY, 'true');
  localStorage.setItem(AUTO_SIGN_FLAG_KEY, 'true');
  // Persist a runtime (URL-supplied) token so it is sent to the backend instead
  // of any build-time token. Lets CI carry the secret and lets prod ship without
  // the token baked into the public bundle.
  if (token) {
    sessionStorage.setItem(AUTO_SIGN_TOKEN_KEY, token);
    localStorage.setItem(AUTO_SIGN_TOKEN_KEY, token);
  }
};

const getStoredAutoSignToken = (): string =>
  sessionStorage.getItem(AUTO_SIGN_TOKEN_KEY) ||
  localStorage.getItem(AUTO_SIGN_TOKEN_KEY) ||
  '';

export const getAutoSignedSession = () =>
  sessionStorage.getItem(AUTO_SIGN_FLAG_KEY) === 'true' ||
  localStorage.getItem(AUTO_SIGN_FLAG_KEY) === 'true';

const readAutoSignTokenFromUrl = (): string | null => {
  if (typeof window === 'undefined') return null;
  const params = new URLSearchParams(window.location.search);
  return params.get('auto_signed');
};

const stripAutoSignFromUrl = () => {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  if (!url.searchParams.has('auto_signed')) return;
  url.searchParams.delete('auto_signed');
  if (window.history && window.history.replaceState) {
    window.history.replaceState({}, document.title, url.toString());
  }
};

const isTrustedAutoSignHost = (): boolean => {
  if (typeof window === 'undefined') return false;
  const hostname = window.location.hostname;
  return TRUSTED_AUTO_SIGN_HOSTS.has(hostname) || TRUSTED_LAN_REGEX.test(hostname);
};

export const tryActivateAutoSign = (): boolean => {
  // Check if URL has auto_signed parameter - enable autoSign for testing if present
  // This allows CI to work without needing to configure tokens at build time
  const urlToken = readAutoSignTokenFromUrl();
  
  // If URL has auto_signed param, activate and remember THAT token — it is what
  // gets sent to the backend (which validates it against its own AUTO_SIGN_TOKEN).
  // This is the CI path and works on any host, enabled flag or not.
  if (urlToken) {
    setAutoSignedSession(urlToken);
    stripAutoSignFromUrl();
    return true;
  }

  if (isTruthy(getAutoSignEnabled()) && isTrustedAutoSignHost()) {
    setAutoSignedSession();
    return true;
  }

  // No URL token - check if already activated in this session
  if (isTruthy(getAutoSignEnabled()) && getAutoSignedSession()) {
    return true;
  }

  clearAutoSignSession();
  return false;
};

export const getAutoSignHeaderToken = (): string | null => {
  // Return the token that activated this session, if auto-sign is active.
  if (!getAutoSignedSession()) return null;

  // Prefer the runtime token that activated the session (URL-supplied, CI) so
  // the credential need not be baked into the public bundle.
  const stored = getStoredAutoSignToken();
  if (stored) return stored;

  const runtimeToken = (import.meta as any).env?.E2E_AUTO_SIGN_TOKEN || '';
  if (runtimeToken) return runtimeToken;

  // Last resort: a build-time token, only present in dev/LAN builds.
  return getAutoSignToken() || null;
};
