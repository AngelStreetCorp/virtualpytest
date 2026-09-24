/**
 * Chart colours for Monitoring > Analytics.
 *
 * Two families, and they are never mixed:
 *
 *   CATEGORICAL — identity. Which alert type, which environment, which area of the
 *   codebase. Slots are assigned in a FIXED order and never cycled; a ninth series
 *   folds into "others" rather than inventing a hue (see topN).
 *
 *   STATUS — state. up/issue/down, pass/fail, incident severity. These are reserved:
 *   a status colour never stands in for "series 4", and a series colour never means
 *   good or bad. Every status mark ships with a visible label, never colour alone.
 *
 * Both modes are SELECTED, not derived. The dark column is the same eight hues
 * re-stepped for a dark surface — flipping lightness programmatically produces
 * colours that fail contrast against #1a1a19. This matters here specifically because
 * the one existing in-app chart (features/avq AVQTimeline) hardcodes dark-only hexes
 * and is unreadable in light mode; do not repeat that.
 *
 * Validated with the dataviz checker in BOTH modes:
 *   light  worst adjacent CVD ΔE 9.1, normal-vision ΔE 19.6 — all checks pass
 *   dark   worst adjacent CVD ΔE 8.4, normal-vision ΔE 19.3 — all checks pass
 * Light mode returns a sub-3:1 contrast warning on three slots (aqua, yellow,
 * magenta). That is not dismissable: every chart using them must carry visible value
 * labels, which is why ChartCard's bar and donut components always render the number
 * beside the mark rather than relying on a tooltip.
 */

export type Mode = 'light' | 'dark';

/** Categorical slots, in assignment order. Never reorder — colour follows the entity. */
const CATEGORICAL: Record<Mode, string[]> = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
};

/**
 * Status colours. Deliberately identical in both modes — a fixed meaning should not
 * shift with the theme, and all four clear 3:1 on the dark surface.
 */
export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
} as const;

export type StatusKey = keyof typeof STATUS;

/** Chart chrome: axes, gridlines, the surface a mark sits on. */
const CHROME: Record<Mode, { grid: string; axis: string; muted: string; track: string; surface: string }> = {
  light: { grid: '#e1e0d9', axis: '#c3c2b7', muted: '#898781', track: '#edece7', surface: '#fcfcfb' },
  dark: { grid: '#2c2c2a', axis: '#383835', muted: '#898781', track: '#262624', surface: '#1a1a19' },
};

export const categorical = (mode: Mode): string[] => CATEGORICAL[mode];

/** Slot n, clamped rather than cycled: past the last slot the caller should fold to "others". */
export const seriesColor = (mode: Mode, index: number): string => {
  const slots = CATEGORICAL[mode];
  return slots[Math.min(index, slots.length - 1)];
};

export const chrome = (mode: Mode) => CHROME[mode];

/** Device fleet state. 'issue' is a real third state, not a shade of down. */
export const DEVICE_STATUS: Record<string, string> = {
  up: STATUS.good,
  issue: STATUS.warning,
  down: STATUS.critical,
};

/** Incident severity. Mapped onto the status ramp so red always means worst. */
export const SEVERITY: Record<string, string> = {
  critical: STATUS.critical,
  high: STATUS.serious,
  medium: STATUS.warning,
  low: STATUS.good,
  unknown: CHROME.dark.muted,
};

/** Host reachability, same ramp. */
export const REACHABILITY: Record<string, string> = {
  reporting: STATUS.good,
  stale: STATUS.warning,
  silent: STATUS.critical,
};

/** Pass/fail is a status, never a category. */
export const OUTCOME: Record<string, string> = {
  passed: STATUS.good,
  failed: STATUS.critical,
};

/**
 * A colour for a named series, stable across re-renders and filters.
 *
 * Keyed by NAME, not by position, so removing a series never repaints the survivors
 * — a reader who learned "freeze is blue" must not find it orange after a filter.
 */
export const colorForNames = (mode: Mode, names: string[]): Record<string, string> => {
  const slots = CATEGORICAL[mode];
  const out: Record<string, string> = {};
  names.forEach((name, i) => {
    out[name] = slots[Math.min(i, slots.length - 1)];
  });
  return out;
};
