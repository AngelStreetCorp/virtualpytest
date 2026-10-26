/**
 * Theme engine (TASK-102): a theme is an accent colour plus a grey tone; the full dark and light
 * palettes (every key the app reads) are derived from those two. A theme may also give exact
 * `dark` / `light` token overrides, which win over the derivation. Status colours (success, error,
 * warning) are fixed and never themed. Pure functions only: no React, no storage.
 */

import { FontId, isFontId } from './themeFonts';
import { SizeId, isSizeId } from './typography';

/** Top-bar hover style. Three values ship today; new ones extend the union, not the data shape.
 *  See `navItemSx` in `frontend/src/components/common/Navigation_ItemStyle.tsx` for the
 *  per-style implementations and the reference render in `docs/agent/platform/UIUX.md`. */
export type NavHoverStyle = 'underline' | 'bracket' | 'magnetic';
export const NAV_HOVER_STYLES: NavHoverStyle[] = ['underline', 'bracket', 'magnetic'];

export interface Palette {
  background: string;
  surface: string;
  /** Opaque twins of `surface` / `sidebarBg` (set by ThemeContext): the same colours while a background image makes the
   *  two above follow card transparency. Use for graph nodes, overlays, toasts and anything floating over content. */
  surfaceSolid: string;
  sidebarBgSolid: string;
  inputBg: string;
  sidebarBg: string;
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  accent: string;
  accentHover: string;
  accentLight: string;
  accentText: string;
  gold: string;
  success: string;
  error: string;
  warning: string;
  agentBubble: string;
  agentBorder: string;
  userBubble: string;
  userBorder: string;
  borderColor: string;
  hoverBg: string;
  cardShadow: string;
  /** Document base layer (html/body, MUI background.default); gold dark keeps its near-black base. */
  pageBackground: string;
  /** MUI background.paper (dialogs, menus, popovers). */
  paperBackground: string;
  /** Label / icon colour on a filled accent surface (buttons, active toggles, badges). */
  onAccent: string;
  /** Tooltip chip background. */
  tooltipBg: string;
  /** Dialog elevation shadow. */
  dialogShadow: string;
  /** SELECTED role (toggle on, active segment, chosen quality): accent tint fill, border, label. */
  selectedBg: string;
  selectedBorder: string;
  selectedText: string;
  /** NEUTRAL role (idle outlined button, toggle off). */
  neutralBorder: string;
  neutralText: string;
  /** DANGER role (destructive action): fixed red family, never themed. */
  dangerBg: string;
  dangerText: string;
  series: string[];
  /** Top-bar hover pattern. Three preconfigured styles today (`navItemSx` in `Navigation_ItemStyle.tsx`);
   *  settable from the theme. Not a colour — sits on `Palette` so consumers read it without a hook. */
  navHover: NavHoverStyle;
}

export type Tone = 'neutral' | 'warm' | 'cool';
export const TONES: Tone[] = ['neutral', 'warm', 'cool'];

export interface ThemeDef {
  id: string;
  name: string;
  accent: string;
  tone: Tone;
  /** Optional dark page colour (#rrggbb); when set the greys are derived from it and `tone` is ignored. */
  background?: string;
  default?: boolean;
  dark?: Partial<Palette>;
  light?: Partial<Palette>;
  /** Optional role colours: `selected` (#rrggbb) recolours only the SELECTED tokens. */
  roles?: { selected?: string };
  /** UI font (TASK-102 G14); unset = classic. A user's own font choice wins over it. */
  font?: FontId;
  /** Non-colour UI options the theme can flip. `navHover` is the top-bar hover pattern;
   *  `size` is TASK-100's UI size scale step (sm/md/lg). The user's own choice wins over either. */
  uiOptions?: { navHover?: NavHoverStyle; size?: SizeId };
}

export interface DerivedPalettes {
  dark: Palette;
  light: Palette;
}

/** Status colours are never themed. */
const FIXED_KEYS = ['success', 'error', 'warning'] as const;
const FIXED_DARK = { success: '#22c55e', error: '#ef4444', warning: '#f59e0b' };
const FIXED_LIGHT = { success: '#16a34a', error: '#dc2626', warning: '#b45309' };

export const GOLD_DARK: Palette = {
  background: '#1a1a1a',
  surface: '#242424',
  surfaceSolid: '#242424',
  inputBg: '#2a2a2a',
  sidebarBg: '#1e1e1e',
  sidebarBgSolid: '#1e1e1e',
  textPrimary: '#f0f0f0',
  textSecondary: '#9a9a9a',
  textMuted: '#666666',
  accent: '#d4a574', // Primary accent - buttons, switches, main UI
  accentHover: '#c49464',
  accentLight: '#e6c39e', // MUI primary.light
  accentText: '#d4a574', // Accent used as text/icon colour (selected item, links)
  gold: '#FFD700', // Bright gold - skills, badges, awards, highlights
  success: '#22c55e',
  error: '#ef4444',
  warning: '#f59e0b', // Run error (infra), not a test failure
  agentBubble: '#262626',
  agentBorder: '#333333',
  userBubble: '#3a3a3a',
  userBorder: '#4a4a4a',
  borderColor: '#383838',
  hoverBg: '#2a2a2a',
  cardShadow: '0 2px 8px rgba(0,0,0,0.3)',
  pageBackground: '#0a0a0a',
  paperBackground: '#1a1a1a',
  onAccent: '#1a1a1a',
  tooltipBg: '#2a2a2a',
  dialogShadow: '0 12px 40px rgba(0,0,0,0.6)',
  selectedBg: 'rgba(212,165,116,0.16)',
  selectedBorder: 'rgba(212,165,116,0.55)',
  selectedText: '#d4a574',
  neutralBorder: '#383838',
  neutralText: '#9a9a9a',
  dangerBg: 'rgba(239,68,68,0.14)',
  dangerText: '#ef4444',
  // Categorical series (one per speaker / line), muted to sit with the accent; never status.
  series: ['#d4a574', '#7aa6c2', '#a98bc7', '#c98b8b', '#8fbf9f'],
  navHover: 'underline',
};

/** Warm grey page (#f2f0ec) so white cards stand out; the top bar is white (ThemeContext). */
export const GOLD_LIGHT: Palette = {
  background: '#f2f0ec',
  surface: '#ffffff',
  surfaceSolid: '#ffffff',
  inputBg: '#ffffff',
  sidebarBg: '#ffffff',
  sidebarBgSolid: '#ffffff',
  textPrimary: '#141414',
  textSecondary: '#4a4a4a',
  textMuted: '#6e6e6e',
  accent: '#d4a574',
  accentHover: '#c49464',
  accentLight: '#e6c39e',
  accentText: '#8f5f2e', // #d4a574 is ~2:1 on white - darker gold for text
  gold: '#b8860b', // #FFD700 is unreadable on white
  success: '#16a34a',
  error: '#dc2626',
  warning: '#b45309',
  agentBubble: '#f7f5f1',
  agentBorder: '#d9d4cc',
  userBubble: '#ebe7e0',
  userBorder: '#cfc9bf',
  borderColor: '#d9d4cc',
  hoverBg: '#ebe7e0',
  cardShadow: '0 1px 3px rgba(60,50,30,0.08)',
  pageBackground: '#f2f0ec',
  paperBackground: '#ffffff',
  onAccent: '#1a1a1a',
  tooltipBg: '#1a1a1a',
  dialogShadow: '0 12px 40px rgba(0,0,0,0.15)',
  selectedBg: 'rgba(212,165,116,0.12)',
  selectedBorder: 'rgba(143,95,46,0.5)',
  selectedText: '#8f5f2e',
  neutralBorder: '#d9d4cc',
  neutralText: '#4a4a4a',
  dangerBg: 'rgba(220,38,38,0.1)',
  dangerText: '#dc2626',
  series: ['#8f5f2e', '#3f6f8f', '#6f5596', '#9a4f4f', '#4f7f5f'],
  navHover: 'underline',
};

/** The built-in theme. Literal dark + light sets keep it pixel-identical to the original palette. */
export const GOLD_THEME: ThemeDef = {
  id: 'gold',
  name: 'Gold',
  accent: GOLD_DARK.accent,
  tone: 'warm',
  font: 'classic',
  dark: GOLD_DARK,
  light: GOLD_LIGHT,
};

// ---- colour maths -------------------------------------------------------------------------

type RGB = [number, number, number];

export const isHex = (v: unknown): v is string => typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v);

const hexToRgb = (hex: string): RGB => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
];

const rgbToHex = ([r, g, b]: RGB): string =>
  '#' +
  [r, g, b]
    .map((c) => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, '0'))
    .join('');

const rgbToHsl = ([r, g, b]: RGB): [number, number, number] => {
  const rn = r / 255, gn = g / 255, bn = b / 255;
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  let h: number;
  if (max === rn) h = ((gn - bn) / d) % 6;
  else if (max === gn) h = (bn - rn) / d + 2;
  else h = (rn - gn) / d + 4;
  return [(h * 60 + 360) % 360, s, l];
};

const hslToHex = (h: number, s: number, l: number): string => {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return rgbToHex([(r + m) * 255, (g + m) * 255, (b + m) * 255]);
};

const luminance = (hex: string): number => {
  const [r, g, b] = hexToRgb(hex).map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

/** WCAG contrast ratio of two #rrggbb colours (1 to 21). */
export const contrast = (a: string, b: string): number => {
  const la = luminance(a), lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
};

/** Text colour (dark or white) that reads best on `bg`, e.g. on a filled accent button. */
export const readableOn = (bg: string): string =>
  contrast(bg, '#1a1a1a') >= contrast(bg, '#ffffff') ? '#1a1a1a' : '#ffffff';

const mix = (a: string, b: string, t: number): string => {
  const x = hexToRgb(a), y = hexToRgb(b);
  return rgbToHex([x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t]);
};

const shiftL = (hex: string, delta: number): string => {
  const [h, s, l] = rgbToHsl(hexToRgb(hex));
  return hslToHex(h, s, Math.max(0, Math.min(1, l + delta)));
};

/** Darken `hex` until it reaches `min`:1 on `bg`. */
const darkenToContrast = (hex: string, bg: string, min: number): string => {
  let out = hex;
  for (let i = 0; i < 60 && contrast(out, bg) < min; i++) out = shiftL(out, -0.02);
  return out;
};

/** Lighten `hex` until it reaches `min`:1 on `bg`. */
const lightenToContrast = (hex: string, bg: string, min: number): string => {
  let out = hex;
  for (let i = 0; i < 60 && contrast(out, bg) < min; i++) out = shiftL(out, 0.02);
  return out;
};

const rgba = (hex: string, a: number): string => {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r},${g},${b},${a})`;
};

/** SELECTED tokens from one colour: tint fill, border, and a label that reads on the tint. */
const selectedTokens = (colour: string, mode: 'dark' | 'light', background: string): Pick<Palette, 'selectedBg' | 'selectedBorder' | 'selectedText'> => ({
  selectedBg: rgba(colour, mode === 'dark' ? 0.16 : 0.12),
  selectedBorder: rgba(colour, 0.5),
  selectedText: mode === 'dark' ? lightenToContrast(colour, background, 4.5) : darkenToContrast(colour, background, 4.5),
});

// ---- derivation ---------------------------------------------------------------------------

/** Grey ramp of a tone: hue and saturation for the dark and the light set (clearly tinted, never faint). */
interface Tint {
  h: number;
  sd: number;
  sl: number;
}

const TONE_TINT: Record<Tone, Tint> = {
  neutral: { h: 215, sd: 0, sl: 0 },
  warm: { h: 35, sd: 0.1, sl: 0.3 },
  cool: { h: 215, sd: 0.2, sl: 0.4 },
};

/** Tint taken from a user-picked dark page colour: its hue, its saturation (floored so a pale light page still shows it). */
const tintFromBackground = (bg: string): Tint & { l: number } => {
  const [h, s, l] = rgbToHsl(hexToRgb(bg));
  const l2 = Math.min(0.3, l);
  return { h, sd: s, sl: s < 0.05 ? 0 : Math.min(0.5, Math.max(0.2, s)), l: l2 };
};

const deriveDark = (accent: string, tint: Tint, baseL: number): Palette => {
  const g = (d: number) => hslToHex(tint.h, tint.sd, Math.max(0, Math.min(1, baseL + d)));
  const t = (l: number) => hslToHex(tint.h, tint.sd, l);
  const background = g(0);
  const accentText = lightenToContrast(accent, background, 4.5);
  return {
    background,
    surface: g(0.04),
    surfaceSolid: g(0.04),
    inputBg: g(0.06),
    sidebarBg: g(0.015),
    sidebarBgSolid: g(0.015),
    textPrimary: t(0.94),
    textSecondary: t(0.62),
    textMuted: t(0.42),
    accent,
    accentHover: shiftL(accent, -0.06),
    accentLight: mix(accent, '#ffffff', 0.4),
    accentText,
    gold: lightenToContrast(accent, background, 7),
    ...FIXED_DARK,
    agentBubble: g(0.045),
    agentBorder: g(0.105),
    userBubble: g(0.115),
    userBorder: g(0.185),
    borderColor: g(0.115),
    hoverBg: g(0.06),
    cardShadow: '0 2px 8px rgba(0,0,0,0.3)',
    pageBackground: background,
    paperBackground: g(0.04),
    onAccent: readableOn(accent),
    tooltipBg: g(0.06),
    dialogShadow: '0 12px 40px rgba(0,0,0,0.6)',
    ...selectedTokens(accent, 'dark', background),
    selectedText: accentText,
    neutralBorder: g(0.115),
    neutralText: t(0.62),
    dangerBg: 'rgba(239,68,68,0.14)',
    dangerText: FIXED_DARK.error,
    series: [accent, '#7aa6c2', '#a98bc7', '#c98b8b', '#8fbf9f'],
    navHover: 'underline',
  };
};

const deriveLight = (accent: string, tint: Tint): Palette => {
  const grey = (l: number) => hslToHex(tint.h, tint.sl, l);
  const accentText = darkenToContrast(accent, '#ffffff', 4.5);
  return {
    background: grey(0.93),
    surface: '#ffffff',
    surfaceSolid: '#ffffff',
    inputBg: '#ffffff',
    sidebarBg: '#ffffff',
    sidebarBgSolid: '#ffffff',
    textPrimary: grey(0.08),
    textSecondary: grey(0.29),
    textMuted: grey(0.43),
    accent,
    accentHover: shiftL(accent, -0.06),
    accentLight: mix(accent, '#ffffff', 0.4),
    accentText,
    gold: darkenToContrast(accent, '#ffffff', 3),
    ...FIXED_LIGHT,
    agentBubble: grey(0.965),
    agentBorder: grey(0.82),
    userBubble: grey(0.9),
    userBorder: grey(0.78),
    borderColor: grey(0.82),
    hoverBg: grey(0.9),
    cardShadow: '0 1px 3px rgba(20,24,28,0.08)',
    pageBackground: grey(0.93),
    paperBackground: '#ffffff',
    onAccent: readableOn(accent),
    tooltipBg: grey(0.08),
    dialogShadow: '0 12px 40px rgba(0,0,0,0.15)',
    ...selectedTokens(accent, 'light', '#ffffff'),
    selectedText: accentText,
    neutralBorder: grey(0.82),
    neutralText: grey(0.29),
    dangerBg: 'rgba(220,38,38,0.1)',
    dangerText: FIXED_LIGHT.error,
    series: [accentText, '#3f6f8f', '#6f5596', '#9a4f4f', '#4f7f5f'],
    navHover: 'underline',
  };
};

/** Drop status keys: they are never themed. */
const withoutFixed = (o: Partial<Palette> | undefined): Partial<Palette> => {
  const copy: Partial<Palette> = { ...(o ?? {}) };
  FIXED_KEYS.forEach((k) => delete copy[k]);
  return copy;
};

/** Full dark and light palettes for a theme: derived from accent + tone, exact overrides win. */
export const derivePalettes = (theme: Pick<ThemeDef, 'accent' | 'tone' | 'dark' | 'light' | 'roles' | 'uiOptions'> & { background?: string }): DerivedPalettes => {
  const accent = isHex(theme.accent) ? theme.accent : GOLD_DARK.accent;
  const tone: Tone = TONES.includes(theme.tone) ? theme.tone : 'neutral';
  // The built-in gold carries literal full sets (including its status colours): use them whole.
  const bg = isHex(theme.background) ? tintFromBackground(theme.background) : null;
  const tint = bg ?? TONE_TINT[tone];
  const baseL = bg ? bg.l : 0.105;
  const baseDark = deriveDark(accent, tint, baseL);
  const baseLight = deriveLight(accent, tint);
  // roles.selected recolours only the SELECTED tokens; explicit dark/light overrides still win.
  const sel = theme.roles?.selected;
  const roleDark = isHex(sel) ? selectedTokens(sel, 'dark', baseDark.background) : {};
  const roleLight = isHex(sel) ? selectedTokens(sel, 'light', '#ffffff') : {};
  const dark = { ...baseDark, ...roleDark, ...(theme === GOLD_THEME ? theme.dark : withoutFixed(theme.dark)) };
  const light = { ...baseLight, ...roleLight, ...(theme === GOLD_THEME ? theme.light : withoutFixed(theme.light)) };
  // uiOptions.navHover overrides the derived default (`'underline'`); wrong values fall back.
  const navHover: NavHoverStyle = NAV_HOVER_STYLES.includes(theme.uiOptions?.navHover as NavHoverStyle)
    ? (theme.uiOptions?.navHover as NavHoverStyle)
    : 'underline';
  dark.navHover = navHover;
  light.navHover = navHover;
  dark.surfaceSolid = dark.surface;
  dark.sidebarBgSolid = dark.sidebarBg;
  light.surfaceSolid = light.surface;
  light.sidebarBgSolid = light.sidebarBg;
  return { dark, light };
};

// ---- validation ---------------------------------------------------------------------------

/** Parse untrusted JSON (server file or storage) into a ThemeDef, or null when it is not one. */
export const parseTheme = (raw: unknown): ThemeDef | null => {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.id !== 'string' || !r.id || typeof r.name !== 'string' || !r.name) return null;
  if (!isHex(r.accent) || !TONES.includes(r.tone as Tone)) return null;
  const overrides = (v: unknown): Partial<Palette> | undefined =>
    v && typeof v === 'object' && !Array.isArray(v) ? (v as Partial<Palette>) : undefined;
  return {
    id: r.id,
    name: r.name,
    accent: r.accent,
    tone: r.tone as Tone,
    background: isHex(r.background) ? r.background.toLowerCase() : undefined,
    default: r.default === true,
    dark: overrides(r.dark),
    light: overrides(r.light),
    font: isFontId(r.font) ? r.font : undefined,
    roles:
      r.roles && typeof r.roles === 'object' && isHex((r.roles as Record<string, unknown>).selected)
        ? { selected: ((r.roles as Record<string, string>).selected).toLowerCase() }
        : undefined,
    uiOptions: (() => {
      const u = r.uiOptions;
      if (!u || typeof u !== 'object') return undefined;
      const v = (u as Record<string, unknown>).navHover;
      const s = (u as Record<string, unknown>).size;
      const navHover = NAV_HOVER_STYLES.includes(v as NavHoverStyle) ? { navHover: v as NavHoverStyle } : {};
      const size = isSizeId(s) ? { size: s } : {};
      return { ...navHover, ...size };
    })(),
  };
};

/**
 * Real readability failures only (empty = fine): the button label (onAccent, chosen by contrast)
 * on the accent below 3:1 (WCAG large / UI text), or body text on the page below 4.5:1.
 * Also 'accent': the accent itself under 1.5:1 on the light cards (borders, icons and outlines vanish).
 * Each entry is a stable code: 'button', 'text' or 'accent', so the UI can name the pair that fails.
 */
export type ContrastIssue = 'button' | 'text' | 'accent';
export const contrastWarnings = (p: DerivedPalettes): ContrastIssue[] => {
  const out = new Set<ContrastIssue>();
  (['dark', 'light'] as const).forEach((m) => {
    const P = p[m];
    if (contrast(P.onAccent, P.accent) < 3) out.add('button');
    if (contrast(P.textPrimary, P.background) < 4.5) out.add('text');
    if (m === 'light' && contrast(P.accent, P.surface) < 1.5) out.add('accent');
  });
  return [...out];
};
