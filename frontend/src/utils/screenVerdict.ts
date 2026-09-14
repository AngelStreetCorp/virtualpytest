/**
 * SINGLE source of truth for turning a Localize verdict into a display label + color.
 *
 * The verdict object is the per-frame `localize` field produced by the backend's
 * identify_screen (via monitor_localize.localize_frame): { node, confidence, excluded,
 * total, state?, state_label? }. It is the SAME shape everywhere it is consumed —
 * the live monitoring overlay (realtime), the AVQ device page (Player = realtime,
 * Frames = the selected frame's JSON), and the Localize popover. Every one of those
 * MUST format it through this function so the screen reads identically across surfaces.
 * (Previously each re-implemented the formatting and they drifted: "unknown" vs
 * "No confident match", stale last-known vs current, etc.)
 */
export interface ScreenVerdict {
  node?: string | null;
  confidence?: number | null;
  excluded?: number | null;
  total?: number | null;
  /** Named capture-side state when no UI node is on screen ('no_signal' | 'blackscreen'). */
  state?: string | null;
  state_label?: string | null;
}

// Confident (green) iff conf >= this AND a single candidate remains — mirrors
// avq_analyze.POS_CONF_GREEN so the backend timeline and the live label agree.
export const SCREEN_CONF_GREEN = 0.55;

export interface ScreenLabel {
  text: string;
  /** MUI sx color: hex or theme token. */
  color: string;
}

// Concrete hex (no MUI theme tokens) so the same value reads on the dark video
// overlay AND the themed AVQ page.
const GREY = '#9e9e9e';

export function formatScreenVerdict(v?: ScreenVerdict | null): ScreenLabel {
  if (!v) return { text: '—', color: GREY }; // no data (Localize disabled / frame not loaded)
  if (v.state) return { text: v.state_label || v.state, color: '#ff7043' }; // No Signal / Black Screen
  if (!v.node) return { text: 'unknown', color: GREY }; // ran, matched no node (e.g. full-screen promo)
  const pct = Math.round((v.confidence ?? 0) * 100);
  const remaining = v.total ? v.total - (v.excluded ?? 0) : 0;
  const confident = (v.confidence ?? 0) >= SCREEN_CONF_GREEN && remaining <= 1;
  return { text: `${v.node} (${pct}%)`, color: confident ? '#4caf50' : '#ffc107' };
}
