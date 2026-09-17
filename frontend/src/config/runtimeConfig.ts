/**
 * Native-shell detection.
 *
 * Runtime env overrides for the mobile app now go through the same mechanism the Docker
 * image uses — `getEnv()` in `./constants.ts`, reading `window.__VPT_CONFIG__` — rather than
 * a separate app-specific global. The native shell serves `/config.js` from stored prefs
 * before the bundle boots (RuntimeConfigWebViewClient in app/.../MainActivity.kt), same as
 * the container entrypoint writes `dist/config.js` from its own environment.
 */
import { getEnv } from './constants';

/**
 * True when the bundle runs inside the Capacitor shell (native app), false on the web.
 *
 * Two independent signals, because the Capacitor one alone is not reliably present at first
 * render on every WebView: `window.Capacitor` only exists once the bridge script the native
 * layer injects into index.html has run, and callers like `MobileBottomNav` read this
 * synchronously while rendering. If the bundle happens to evaluate first, the app silently
 * falls back to its web behaviour for the rest of the session (no "This phone" tab) — the
 * whole point of the `VITE_IS_NATIVE_APP` flag below.
 *
 * `/config.js` is served by the native shell itself (RuntimeConfigWebViewClient) and
 * index.html requests it as a classic script before the module bundle, so the flag is set
 * before any React code runs no matter how the bridge injection is ordered. Prefer it; keep
 * the bridge check as the fallback for a shell too old to send the flag.
 *
 * Note this answers "are we inside the APK", NOT "can I call the native plugin" — for that
 * see `isPhoneAgentAvailable()` in features/mobile-app/frontend/native/phoneAgent.ts, which
 * needs the bridge itself and so stays a `window.Capacitor` check.
 */
export const isNativeApp = (): boolean => {
  if (getEnv('VITE_IS_NATIVE_APP') === 'true') return true;
  try {
    const cap = (window as any).Capacitor;
    return Boolean(cap?.isNativePlatform?.());
  } catch {
    return false;
  }
};
