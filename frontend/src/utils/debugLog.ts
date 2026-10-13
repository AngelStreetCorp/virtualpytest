/**
 * Opt-in debug logging for hot-path components.
 *
 * Why this exists: the HLS player logs ~50 lifecycle traces per stream
 * (mount, manifest parsed, resume, cleanup, watchdog…). On a page that mounts
 * several previews — device-control, rec, fullscreen — that is hundreds of
 * console lines that bury the lines that actually matter: real `console.warn`
 * errors, failed requests, and warnings from third-party code such as noVNC.
 *
 * The contract:
 *   - `debugLog(...)` is silent by default, in dev and in production alike.
 *   - Turn it on at runtime from the browser console, no rebuild needed:
 *       window.__VPT_DEBUG_HLS__ = true
 *   - `console.warn` / `console.error` are NOT affected. Those stay on: they
 *     signal real failures and must never be gated behind a flag.
 *
 * This mirrors the opt-in gate already used by `vncUtils.ts`
 * (`window.__VPT_DEBUG_VNC_SCALE__`); keep the `__VPT_DEBUG_*` naming so a
 * single console paste enables everything.
 */
export function debugLog(...args: unknown[]): void {
  if (typeof window !== 'undefined' && (window as { __VPT_DEBUG_HLS__?: boolean })?.__VPT_DEBUG_HLS__ === true) {
    console.log(...args);
  }
}

/**
 * Test seam: lets unit tests assert that a trace is suppressed/enabled without
 * poking at `window`. Production code should call `debugLog`, not this.
 */
export function setDebugLoggingEnabled(enabled: boolean): void {
  if (typeof window === 'undefined') return;
  (window as { __VPT_DEBUG_HLS__?: boolean }).__VPT_DEBUG_HLS__ = enabled;
}