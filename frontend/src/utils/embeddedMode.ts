/**
 * True when the app runs inside a frame of itself (split view's second page, TASK-77).
 * An embedded app draws only the page: no top bar, footer, floating AI button or mods.
 * `?embed=1` asks for the same (Atlas Companion, TASK-126), also outside a frame.
 * Checked once at load, so in-page navigation keeps it; a cross-origin parent also counts as embedded.
 */
export const isEmbedded: boolean = (() => {
  try {
    return window.self !== window.top || new URLSearchParams(window.location.search).get('embed') === '1';
  } catch {
    return true;
  }
})();
