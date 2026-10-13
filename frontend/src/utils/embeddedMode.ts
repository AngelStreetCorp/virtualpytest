/**
 * True when the app runs inside a frame of itself (split view's second page, TASK-77).
 * An embedded app draws only the page: no top bar, footer, floating AI button or mods.
 * Checked once at load; a cross-origin parent (not ours) also counts as embedded.
 */
export const isEmbedded: boolean = (() => {
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
})();
