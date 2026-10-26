/**
 * SINGLE source of truth for turning a Localize verdict into a display label + color.
 *
 * The verdict object is the per-frame `localize` field produced by the backend's
 * identify_screen (via monitor_localize.localize_frame): { node, confidence, excluded,
 * total, tier?, reason?, door?, state?, state_label?, gate_skip?, loaded?, overlay?,
 * playback?, error? }. It is the SAME shape everywhere it is consumed — the live
 * monitoring overlay (realtime), the AVQ device page (Player = realtime, Frames =
 * the selected frame's JSON), and the Localize popover. Every one of those MUST
 * format it through this function so the screen reads identically across surfaces.
 * (Previously each re-implemented the formatting and they drifted: "unknown" vs
 * "No confident match", stale last-known vs current, etc.)
 *
 * `tier`/`reason`/`door` are ADDITIVE and optional: frames written before the backend
 * reported them (archived captures read through the AVQ Frames tab) carry none, so every
 * reader must treat all three as absent rather than assume them. The Tier-2 fields
 * (`loaded`/`overlay`/`playback`/`error`, from `shared.src.lib.ai.screen_state_cv`) are
 * ALSO additive: only present on a fresh matcher run (the motion gate skips them on
 * a gate-skip frame), and absent on frames written before the cascade landed. A
 * `gate_skip` frame carries the cached `node` with `confidence: 0` and no Tier-2
 * fields — format the same way as a regular match, but treat the 0 confidence as
 * "we did not measure this frame" (the colour stays neutral, not the match-amber).
 *
 * Priority for the primary label (from backend docs/agent/navigation/FINGERPRINT.md,
 * with the LOADED arm narrowed to "no" only — see the 2026-10-11 fix):
 *   state (capture-side) > error == 'visible' > overlay != 'none' >
 *   playback in {playing, paused} > loaded == 'no' > node
 * The first arm that fires wins; lower-priority arms move into the `badges` list so
 * a node label is still visible when a Tier-2 field claims the primary.
 */
import { AGENT_CHAT_PALETTE } from '../constants/agentChatTheme';

export interface ScreenVerdict {
  node?: string | null;
  confidence?: number | null;
  excluded?: number | null;
  total?: number | null;
  /** Named capture-side state when no UI node is on screen ('no_signal' | 'blackscreen'). */
  state?: string | null;
  state_label?: string | null;
  /** Matcher layer that answered: 'rule' today, 'cv'/'model' reserved. */
  tier?: string | null;
  /** identify_screen's own abstain reason, verbatim. */
  reason?: string | null;
  /** Abstain door mapped from `reason` by the backend: '1'..'6' | 'unknown'. */
  door?: string | null;
  /** Motion-gate skip reason: 'live' (full-frame motion) or 'motion' (band / minor > 1%). */
  gate_skip?: string | null;
  /** Tier 2 — only present on a fresh matcher run (the gate must be open to read the frame). */
  loaded?: 'yes' | 'no' | 'unknown' | null;
  overlay?: 'none' | 'popup' | 'tooltip' | 'keyboard' | 'notification' | 'unknown' | null;
  playback?: 'playing' | 'paused' | 'stopped' | 'not_applicable' | 'unknown' | null;
  error?: 'none' | 'visible' | 'unknown' | null;
  /** Localize v3 verdict kind (TASK-104) — the same answer the Localize button and MCP give. */
  kind?: LocalizeKind | null;
  verdict?: { kind: LocalizeKind; label: string; node_id?: string | null; confidence?: number; evidence?: { named?: boolean; state?: string } | null } | null;
}

export type LocalizeKind = 'signal' | 'live' | 'node' | 'overlay' | 'known_screen' | 'app' | 'unknown';

// Confident (green) iff conf >= this AND a single candidate remains — mirrors
// avq_analyze.POS_CONF_GREEN so the backend timeline and the live label agree.
export const SCREEN_CONF_GREEN = 0.55;

export interface ScreenLabel {
  text: string;
  /** MUI sx color: hex or theme token. */
  color: string;
  /**
   * Secondary Tier-2 badges, in priority order (error -> overlay -> playback -> loaded).
   * Empty when the per-frame payload has no Tier-2 fields (older frames, gate-skip
   * frames). Each badge is rendered as a small inline tag next to the primary text.
   */
  badges?: ScreenLabel[];
}

// Static palette: this is a non-React utility, and the same value must read on the dark
// video overlay AND the themed AVQ page (light or dark) — a non-mode-switching hex keeps
// it readable on a video frame regardless of UI theme.
const GREY = '#9e9e9e';
const STATE_COLOR = '#ff7043'; // captured on the video frame, must read on dark imagery
const CONFIDENT = AGENT_CHAT_PALETTE.success;
const NOT_CONFIDENT = '#ffc107'; // palette: amber kept as warning on the live overlay
// Tier-2 colour tokens. Distinct from the match colours above so a "playing" badge
// cannot be confused with a confident match, and an "Error" badge cannot be confused
// with a state colour. Kept static for the same reason as the match colours — must
// read on dark imagery and on a light AVQ page.
const T2_ERROR = '#e53935';     // alert: error visible on screen
const T2_OVERLAY = '#8d6e63';   // muted warning: popup / tooltip / keyboard / notification
const T2_PLAYBACK = '#607d8b';  // dim: playing / paused / stopped
const T2_LOADED = '#78909c';    // dim: yes / no

const UNKNOWN_T2 = 'unknown';

function _t2(v: ScreenVerdict['error']): string {
  // Only 'visible' is a real signal — 'none' is the absence of an error and must NOT
  // claim the primary label (otherwise every healthy frame renders as 'Error: none'
  // and the matched node is hidden behind a badge). Same for 'unknown' / null.
  if (v === 'visible') return 'visible';
  return '';
}

function _t2Overlay(v: ScreenVerdict['overlay']): string {
  if (!v || v === 'none' || v === UNKNOWN_T2) return '';
  return v;
}

function _t2Playback(v: ScreenVerdict['playback']): string {
  if (!v) return '';
  if (v === 'playing' || v === 'paused') return v;
  return '';
}

function _t2Loaded(v: ScreenVerdict['loaded']): string {
  // Only 'no' (still loading) claims the primary — it is a transient state worth
  // surfacing. 'yes' is the NORMAL state on a settled screen and must NOT shadow
  // the matched node label; it drops to the badges list instead.
  if (v === 'no') return 'loading…';
  return '';
}

function _tier2Badges(v: ScreenVerdict): ScreenLabel[] {
  const badges: ScreenLabel[] = [];
  const e = _t2(v.error);
  if (e) badges.push({ text: `error: ${e}`, color: T2_ERROR });
  const o = _t2Overlay(v.overlay);
  if (o) badges.push({ text: `overlay: ${o}`, color: T2_OVERLAY });
  const p = _t2Playback(v.playback);
  if (p) badges.push({ text: p, color: T2_PLAYBACK });
  // 'yes' here is the normal settled state — _t2Loaded did not claim primary for it, so
  // we surface it as a subtle dim badge. 'no' is owned by the primary label.
  if (v.loaded === 'yes') badges.push({ text: 'loaded', color: T2_LOADED });
  return badges;
}

/**
 * A known_screen the backend could not name: evidence.named === false, no label, or (hosts that predate the flag,
 * BUG-0663) the generic "Known screen (unknown, seen Nx)" text.
 */
export function isUnnamedKnownScreen(v?: { label?: string | null; evidence?: { named?: boolean } | null } | null): boolean {
  return !v || !v.label || v.evidence?.named === false || /^Known screen \(unknown\b/i.test(v.label);
}

/** The registry's placeholder name `unknown_49` reads "Unnamed screen 49" (TASK-159); any other label is unchanged. */
export function screenDisplayName(label: string): string {
  const m = /^unknown_(\d+)$/.exec(label);
  return m ? `Unnamed screen ${m[1]}` : label;
}

/** Returns null when Localize named nothing worth showing (owner 2026-10-19: unknown = show nothing). */
export function formatScreenVerdict(v?: ScreenVerdict | null): ScreenLabel | null {
  if (!v) return null; // no data (Localize disabled / frame not loaded)
  // Tier-2 priority arms first — the first one that fires owns the primary text,
  // and the rest (if any) drop into `badges`. State stays at the very top because
  // it is a capture-side reality, not a Tier-2 inference.
  const e = _t2(v.error);
  if (e) return { text: `Error: ${e}`, color: T2_ERROR, badges: _tier2Badges(v) };
  // Localize v3 kinds that are not a node match read as the verdict's own label, exactly as the
  // Localize button and the MCP tool name them ("Live video", "Popup over home", "Known screen …").
  if (v.verdict && (v.kind === 'live' || v.kind === 'overlay' || v.kind === 'known_screen' || v.kind === 'app')) {
    if (v.kind === 'known_screen' && isUnnamedKnownScreen(v.verdict)) return null;
    const color = v.kind === 'overlay' ? T2_OVERLAY : v.kind === 'live' ? T2_PLAYBACK : T2_LOADED; // app and known_screen read dim
    return { text: screenDisplayName(v.verdict.label), color, badges: _tier2Badges(v) };
  }
  const o = _t2Overlay(v.overlay);
  if (o) return { text: `Overlay: ${o}`, color: T2_OVERLAY, badges: _tier2Badges(v) };
  const p = _t2Playback(v.playback);
  if (p) return { text: p, color: T2_PLAYBACK, badges: _tier2Badges(v) };
  const l = _t2Loaded(v.loaded);
  if (l) return { text: l, color: T2_LOADED, badges: _tier2Badges(v) };
  if (v.state) return { text: v.state_label || v.state, color: STATE_COLOR }; // No Signal / Black Screen
  if (!v.node) return null; // ran, matched no node (e.g. full-screen promo): show nothing
  const pct = Math.round((v.confidence ?? 0) * 100);
  const remaining = v.total ? v.total - (v.excluded ?? 0) : 0;
  // On a gate_skip frame the matcher did NOT measure this frame: confidence is 0
  // by contract. We still show the cached node label so the overlay does not
  // blank, but the colour stays neutral — never confuse a cached label with a
  // freshly-matched one.
  const isGateSkip = !!v.gate_skip;
  const confident = !isGateSkip && (v.confidence ?? 0) >= SCREEN_CONF_GREEN && remaining <= 1;
  const out: ScreenLabel = {
    text: `${v.node} (${pct}%)`,
    color: isGateSkip ? GREY : confident ? CONFIDENT : NOT_CONFIDENT,
  };
  const badges = _tier2Badges(v);
  if (badges.length) out.badges = badges;
  return out;
}

// ── Diagnosis: which layer answered, and WHY it abstained ─────────────────────
// The matcher (identify_screen) drops candidates through six ordered "doors"; an empty
// result is an ABSTAIN, i.e. normal behaviour, not a fault. So every label below is
// matter-of-fact and the colour stays grey — an abstain must never read as an error.
// Keep this table in step with docs/agent/navigation/FINGERPRINT.md and with
// _ABSTAIN_DOOR_REASONS in backend_host/scripts/monitor_localize.py (which maps the
// matcher's reason string to the door id). 'unknown' = a reason the backend could not map.
const ABSTAIN_DOOR_LABELS: Record<string, string> = {
  '1': 'blank / too little detail',
  '2': 'underline matched no node',
  '3': 'underline not on menu chrome',
  '4': 'title picked no screen',
  '5': 'closest nodes too far apart',
  '6': 'nearest match too weak',
  '7': 'marked as not this screen',
  unknown: 'no recognizable screen',
};

// 'cv' and 'model' are reserved by the backend (this path only ever runs the
// deterministic dHash/focus layers), so they are named here and nothing else.
const TIER_LABELS: Record<string, string> = { rule: 'rule', cv: 'cv', model: 'model' };

export interface ScreenDiagnosis {
  /** Matcher layer that answered ('rule' today), or null when not reported. */
  tier: string | null;
  /** Human phrase for the abstain door, or null when there was no abstain. */
  door: string | null;
  /** identify_screen's raw reason, verbatim — for surfaces with room (popover, AVQ). */
  reason: string | null;
  /** MUI sx color for the tier/door text. */
  color: string;
}

/**
 * The one-line "how was this decided, and why did it abstain" detail.
 * Returns null when the payload carries no diagnosis at all (older frames, or a
 * clean match with no abstain) so callers render nothing extra.
 */
export function formatScreenDiagnosis(v?: ScreenVerdict | null): ScreenDiagnosis | null {
  if (!v) return null;
  const rawTier = (v.tier || '').trim().toLowerCase();
  const tier = rawTier ? TIER_LABELS[rawTier] ?? rawTier : null;
  const rawDoor = (v.door || '').trim().toLowerCase();
  const door = rawDoor ? ABSTAIN_DOOR_LABELS[rawDoor] ?? ABSTAIN_DOOR_LABELS.unknown : null;
  if (!tier && !door) return null;
  return { tier, door, reason: v.reason ?? null, color: door ? GREY : '#888888' };
}
