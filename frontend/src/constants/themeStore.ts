/**
 * Theme persistence and resolution (TASK-102). Browser storage only; every access is wrapped
 * because storage can be unavailable (private windows, blocked site data).
 */
import { FontId, isFontId } from './themeFonts';
import { GOLD_THEME, ThemeDef, Tone, isHex, parseTheme, TONES } from './themeEngine';
import { SizeId, isSizeId, DEFAULT_SIZE } from './typography';

export const CUSTOM_KEY = 'virtualpytest:theme:custom';
export const SELECTED_KEY = 'virtualpytest:theme:selected';
/** Last provided themes the server returned, so the first paint already has them. */
export const PROVIDED_KEY = 'virtualpytest:theme:provided';

/** The user's own font choice; absent = use the theme's font. */
export const FONT_KEY = 'virtualpytest:theme:font';

/** TASK-100: the user's chosen UI size scale (sm / md / lg). Absent = the theme's size (default md). */
export const SIZE_KEY = 'virtualpytest:theme:size';

export const CUSTOM_ID = 'custom';

export interface CustomThemeInput {
  name: string;
  accent: string;
  tone: Tone;
  /** Optional dark page colour; unset = derived from tone. */
  background?: string;
}

const read = (key: string): unknown => {
  try {
    const v = localStorage.getItem(key);
    return v === null ? null : JSON.parse(v);
  } catch {
    return null;
  }
};

const write = (key: string, value: unknown | null): void => {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable */
  }
};

export const loadCustom = (): CustomThemeInput | null => {
  const r = read(CUSTOM_KEY) as Record<string, unknown> | null;
  if (!r || typeof r.name !== 'string' || !r.name || !isHex(r.accent) || !TONES.includes(r.tone as Tone)) return null;
  return {
    name: r.name,
    accent: r.accent,
    tone: r.tone as Tone,
    ...(isHex(r.background) ? { background: r.background } : {}),
  };
};
export const saveCustom = (c: CustomThemeInput | null): void => write(CUSTOM_KEY, c);

export const loadSelected = (): string | null => {
  const v = read(SELECTED_KEY);
  return typeof v === 'string' ? v : null;
};
export const saveSelected = (id: string): void => write(SELECTED_KEY, id);

export const loadProvided = (): ThemeDef[] => {
  const v = read(PROVIDED_KEY);
  return Array.isArray(v) ? v.map(parseTheme).filter((t): t is ThemeDef => t !== null) : [];
};
export const saveProvided = (themes: ThemeDef[]): void => write(PROVIDED_KEY, themes);

export const customToTheme = (c: CustomThemeInput): ThemeDef => ({ id: CUSTOM_ID, name: c.name, accent: c.accent, tone: c.tone, background: c.background });

/** Every selectable theme, in menu order: gold, the provided ones, then the user's own. */
export const listThemes = (provided: ThemeDef[], custom: CustomThemeInput | null): ThemeDef[] => [
  GOLD_THEME,
  ...provided.filter((t) => t.id !== GOLD_THEME.id && t.id !== CUSTOM_ID),
  ...(custom ? [customToTheme(custom)] : []),
];

/** The user's selected theme if it still exists, else the install default, else gold. */
export const resolveTheme = (themes: ThemeDef[], selectedId: string | null): ThemeDef =>
  themes.find((t) => t.id === selectedId) ?? themes.find((t) => t.default) ?? GOLD_THEME;

export const loadUserFont = (): FontId | null => {
  const v = read(FONT_KEY);
  return isFontId(v) ? v : null;
};
export const saveUserFont = (f: FontId | null): void => write(FONT_KEY, f);

/** Per-user navbar hover style. Independent of the theme — UI choice, not a colour. */
export const NAV_HOVER_KEY = 'virtualpytest:ui:navHover';

const NAV_HOVER_VALUES = ['underline', 'bracket', 'magnetic'] as const;
export type UserNavHover = (typeof NAV_HOVER_VALUES)[number];

export const loadUserNavHover = (): UserNavHover => {
  const v = read(NAV_HOVER_KEY);
  return (NAV_HOVER_VALUES as readonly string[]).includes(v as string) ? (v as UserNavHover) : 'underline';
};
export const saveUserNavHover = (s: UserNavHover): void => write(NAV_HOVER_KEY, s);

/** The user's chosen UI scale; null = the theme wins, then DEFAULT_SIZE. */
export const loadUserSize = (): SizeId | null => {
  const v = read(SIZE_KEY);
  return isSizeId(v) ? v : null;
};
export const saveUserSize = (s: SizeId): void => write(SIZE_KEY, s);

/** Active size: user's pick wins over the theme's, then DEFAULT_SIZE. */
export const resolveSize = (userSize: SizeId | null, themeSize?: SizeId): SizeId => userSize ?? themeSize ?? DEFAULT_SIZE;
