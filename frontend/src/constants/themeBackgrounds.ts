/**
 * Background images (TASK-136). Each mode (light, dark) keeps its own background: an image (`none`, one
 * of that mode's two presets, or `custom` = the user's one image, kept in IndexedDB under one fixed key),
 * a tint (`theme` = the Colours accent, or a fixed colour), the image transparency (the veil over the
 * image) and the card transparency. The Theme choice (light / dark / system) decides which set applies.
 * Presets painted in gold are tinted with a CSS filter; Nebula and the user's image are never tinted.
 * Browser storage only; every access is wrapped (private windows, blocked site data).
 */

export type BgMode = 'dark' | 'light';

export interface BackgroundPreset {
  id: string;
  name: string;
  /** 'any' = a library image, offered in both modes. */
  mode: BgMode | 'any';
  /** Hue (degrees) the art was painted in; null = multi-colour, never tinted. */
  baseHue: number | null;
  /** Mean relative luminance (0-1), measured once on the shipped file; drives the extra veil. */
  luma: number;
}

/** Saturation of the gold the art was painted in (#d4a574). */
const BASE_SAT = 0.53;

/** Two per mode; the menu and the dialog offer only the current mode's. */
export const BACKGROUND_PRESETS: BackgroundPreset[] = [
  { id: 'nebula-dark', name: 'Nebula', mode: 'dark', baseHue: null, luma: 0.044 },
  { id: 'ember-dark', name: 'Amber', mode: 'dark', baseHue: 32, luma: 0.048 },
  { id: 'dawn-light', name: 'Dawn', mode: 'light', baseHue: 32, luma: 0.776 },
  { id: 'contour-light', name: 'Contour', mode: 'light', baseHue: 32, luma: 0.875 },
];

/**
 * The library: photos and art (2560 x 1440 WebP in /backgrounds/library/), offered in both modes from the
 * dialog's Library button. Never tinted; the veil follows each file's luma like any preset.
 */
export const LIBRARY_PRESETS: BackgroundPreset[] = [
  { id: 'coder', name: 'Coder', mode: 'any', baseHue: null, luma: 0.105 },
  { id: 'patagonia', name: 'Patagonia', mode: 'any', baseHue: null, luma: 0.256 },
  { id: 'alpine-lake', name: 'Alpine Lake', mode: 'any', baseHue: null, luma: 0.160 },
  { id: 'terminal', name: 'Terminal', mode: 'any', baseHue: null, luma: 0.027 },
  { id: 'meadow', name: 'Meadow', mode: 'any', baseHue: null, luma: 0.297 },
  { id: 'forest-stream', name: 'Forest Stream', mode: 'any', baseHue: null, luma: 0.054 },
  { id: 'aurora', name: 'Aurora', mode: 'any', baseHue: null, luma: 0.066 },
  { id: 'forest-lake', name: 'Forest Lake', mode: 'any', baseHue: null, luma: 0.061 },
  { id: 'violet-wave', name: 'Violet Wave', mode: 'any', baseHue: null, luma: 0.039 },
  { id: 'desert-ridges', name: 'Desert Ridges', mode: 'any', baseHue: null, luma: 0.132 },
  { id: 'mountain-sunset', name: 'Mountain Sunset', mode: 'any', baseHue: null, luma: 0.133 },
  { id: 'neon-swirl', name: 'Neon Swirl', mode: 'any', baseHue: null, luma: 0.348 },
  { id: 'glitter', name: 'Glitter', mode: 'any', baseHue: null, luma: 0.508 },
  { id: 'ice', name: 'Ice', mode: 'any', baseHue: null, luma: 0.120 },
  { id: 'city-night', name: 'City Night', mode: 'any', baseHue: null, luma: 0.028 },
  { id: 'halftone-blue', name: 'Halftone Blue', mode: 'any', baseHue: null, luma: 0.155 },
  { id: 'links', name: 'Links', mode: 'any', baseHue: null, luma: 0.147 },
  { id: 'dream-tree', name: 'Dream Tree', mode: 'any', baseHue: null, luma: 0.235 },
  { id: 'pink-rings', name: 'Pink Rings', mode: 'any', baseHue: null, luma: 0.141 },
  { id: 'red-rim', name: 'Red Rim', mode: 'any', baseHue: null, luma: 0.053 },
  { id: 'red-planet', name: 'Red Planet', mode: 'any', baseHue: null, luma: 0.025 },
  { id: 'orange-waves', name: 'Orange Waves', mode: 'any', baseHue: null, luma: 0.275 },
  { id: 'dunes', name: 'Dunes', mode: 'any', baseHue: null, luma: 0.188 },
];

export const BG_NONE = 'none';
/** The user's own image. */
export const BG_CUSTOM = 'custom';
/** Tint = the accent of the Colours choice. */
export const TINT_THEME = 'theme';
/** No tint: the image in its own colours. */
export const TINT_ORIGINAL = 'original';

/** Fixed tint colours offered next to "Theme" (owner mockup, 2026-10-19). */
export const TINT_COLOURS = ['#d4a574', '#e5484d', '#7c6cf0', '#3fb8af', '#5bb974', '#4c8dff', '#9a9a9a'];

export const isLibraryPreset = (id: string): boolean => LIBRARY_PRESETS.some((p) => p.id === id);

export const presetUrl = (id: string): string => (isLibraryPreset(id) ? `/backgrounds/library/${id}.webp` : `/backgrounds/${id}.webp`);

/** 320 x 180 thumbnail of a library image (the grid and the swatches never load the 2560 px file). */
export const libraryThumbUrl = (id: string): string => `/backgrounds/library/thumb/${id}.webp`;

export const findPreset = (id: string): BackgroundPreset | undefined =>
  BACKGROUND_PRESETS.find((p) => p.id === id) ?? LIBRARY_PRESETS.find((p) => p.id === id);

export const presetsFor = (mode: BgMode): BackgroundPreset[] => BACKGROUND_PRESETS.filter((p) => p.mode === mode);

// ---- tint ---------------------------------------------------------------------------------

const hexToHs = (hex: string): { h: number; s: number } | null => {
  if (!/^#[0-9a-fA-F]{6}$/.test(hex)) return null;
  const n = parseInt(hex.slice(1), 16);
  const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  if (!d) return { h: 0, s: 0 };
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: (h * 60 + 360) % 360, s };
};

/** CSS filter turning the gold art into `accent`: rotate by the hue gap, scale saturation (grey accent = 0). */
export const tintFilter = (preset: BackgroundPreset | undefined, accent: string | null): string => {
  if (!accent || !preset || preset.baseHue === null) return 'none';
  const a = hexToHs(accent);
  if (!a) return 'none';
  const rot = Math.round(((a.h - preset.baseHue + 540) % 360) - 180);
  const sat = Math.min(1.4, a.s / BASE_SAT).toFixed(2);
  return `hue-rotate(${rot}deg) saturate(${sat})`;
};

/** Below this mean luminance an image is too dark for light mode's dark page text. */
export const LIGHT_MODE_MAX_DARKNESS = 0.45;
/** Above this mean luminance an image is too bright for dark mode's light page text. */
export const DARK_MODE_MAX_BRIGHTNESS = 0.4;
/** Veil added on top of the user's image transparency when the image does not suit the mode. */
const CLASH_EXTRA_VEIL = 0.35;
const MAX_VEIL = 0.95;

/** Veil over the image, in the page colour: the user's image transparency, plus 35 % when the image
 *  does not suit the mode (a dark image in light mode, a bright one in dark mode) so page text stays
 *  readable. Same rule for presets and the user's image; unknown luma = no extra. */
export const veilAlpha = (imageTransparency: number, luma: number | undefined, mode: BgMode): number => {
  const clash = luma !== undefined && (mode === 'light' ? luma < LIGHT_MODE_MAX_DARKNESS : luma > DARK_MODE_MAX_BRIGHTNESS);
  return Math.min(MAX_VEIL, imageTransparency / 100 + (clash ? CLASH_EXTRA_VEIL : 0));
};

const toLinear = (c: number): number => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
};

/** Mean relative luminance (0-1, WCAG weights on linear RGB) of an image, sampled at 64 x 36. */
export const measureLuma = (source: CanvasImageSource): number | null => {
  const c = document.createElement('canvas');
  c.width = 64;
  c.height = 36;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  if (!ctx) return null;
  ctx.drawImage(source, 0, 0, 64, 36);
  const d = ctx.getImageData(0, 0, 64, 36).data;
  let sum = 0;
  for (let i = 0; i < d.length; i += 4) sum += 0.2126 * toLinear(d[i]) + 0.7152 * toLinear(d[i + 1]) + 0.0722 * toLinear(d[i + 2]);
  return Math.round((sum / (d.length / 4)) * 1000) / 1000;
};

/** Luma of a stored blob (an image saved before luma was recorded). */
export const measureBlobLuma = async (blob: Blob): Promise<number | null> => {
  try {
    const bitmap = await createImageBitmap(blob);
    const l = measureLuma(bitmap);
    bitmap.close();
    return l;
  } catch {
    return null;
  }
};

export const isLuma = (v: unknown): v is number => typeof v === 'number' && v >= 0 && v <= 1;

// ---- per-mode settings (localStorage) ------------------------------------------------------

export const IMAGE_TRANSPARENCY_MAX = 90;
export const CARD_TRANSPARENCY_MAX = 60;

export interface ModeBackground {
  /** `none`, a preset id of this mode, or `custom` (the user's image). */
  img: string;
  /** `theme` (the Colours accent) or a fixed #rrggbb. */
  tint: string;
  /** Veil over the image, 0-90 %. */
  imageTransparency: number;
  /** Card transparency over the image, 0-60 %. */
  cardTransparency: number;
}

export interface BackgroundSettings {
  light: ModeBackground;
  dark: ModeBackground;
  /** Mean relative luminance (0-1) of the user's image, measured at upload. */
  customLuma?: number;
}

export const DEFAULT_MODE_BACKGROUND: ModeBackground = { img: BG_NONE, tint: TINT_THEME, imageTransparency: 35, cardTransparency: 18 };

export const defaultBackgrounds = (): BackgroundSettings => ({ light: { ...DEFAULT_MODE_BACKGROUND }, dark: { ...DEFAULT_MODE_BACKGROUND } });

export const BACKGROUNDS_KEY = 'virtualpytest:theme:backgrounds';

/**
 * Colour laid over an image that is not painted in gold (multi-colour presets, library, the user's
 * image): blended with `mix-blend-mode: color`, so light and shade stay and only the hue changes.
 */
export const tintOverlay = (preset: BackgroundPreset | undefined, accent: string | null): string | null =>
  accent && (!preset || preset.baseHue === null) ? accent : null;

/** The colour a tint choice paints in: the accent for Theme, null for Original, else the fixed colour. */
export const tintColour = (tint: string, accent: string): string | null => (tint === TINT_ORIGINAL ? null : tint === TINT_THEME ? accent : tint);

const pct = (v: unknown, max: number, fallback: number): number =>
  typeof v === 'number' && Number.isFinite(v) ? Math.round(Math.min(max, Math.max(0, v))) : fallback;

const parseMode = (v: unknown, mode: BgMode): ModeBackground => {
  const r = (v && typeof v === 'object' ? v : {}) as Record<string, unknown>;
  const preset = typeof r.img === 'string' ? findPreset(r.img) : undefined;
  return {
    img: r.img === BG_CUSTOM || preset?.mode === mode || preset?.mode === 'any' ? (r.img as string) : BG_NONE,
    tint: r.tint === TINT_ORIGINAL ? TINT_ORIGINAL : typeof r.tint === 'string' && /^#[0-9a-fA-F]{6}$/.test(r.tint) ? r.tint : TINT_THEME,
    imageTransparency: pct(r.imageTransparency, IMAGE_TRANSPARENCY_MAX, DEFAULT_MODE_BACKGROUND.imageTransparency),
    cardTransparency: pct(r.cardTransparency, CARD_TRANSPARENCY_MAX, DEFAULT_MODE_BACKGROUND.cardTransparency),
  };
};

export const loadBackgrounds = (): BackgroundSettings => {
  try {
    const raw = localStorage.getItem(BACKGROUNDS_KEY);
    const r = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    return {
      light: parseMode(r.light, 'light'),
      dark: parseMode(r.dark, 'dark'),
      ...(isLuma(r.customLuma) ? { customLuma: r.customLuma } : {}),
    };
  } catch {
    return defaultBackgrounds();
  }
};

export const saveBackgrounds = (b: BackgroundSettings): void => {
  try {
    localStorage.setItem(BACKGROUNDS_KEY, JSON.stringify(b));
  } catch {
    /* storage unavailable */
  }
};

// ---- the user's image (IndexedDB, one fixed key) -------------------------------------------

const DB_NAME = 'virtualpytest-backgrounds';
const STORE = 'images';
/** One key: saving an upload overwrites it, so a user never has more than one image. */
const IMAGE_KEY = 'virtualpytest:theme:image';

const openDb = (): Promise<IDBDatabase> =>
  new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

const tx = async <T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest): Promise<T | null> => {
  try {
    const db = await openDb();
    return await new Promise<T | null>((resolve) => {
      const req = run(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve((req.result as T) ?? null);
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
};

export const loadThemeImage = (): Promise<Blob | null> =>
  tx<Blob>('readonly', (s) => s.get(IMAGE_KEY)).then((b) => (b instanceof Blob ? b : null));

export const saveThemeImage = async (blob: Blob): Promise<boolean> =>
  (await tx('readwrite', (s) => s.put(blob, IMAGE_KEY))) !== null;

export const deleteThemeImage = async (): Promise<void> => {
  await tx('readwrite', (s) => s.delete(IMAGE_KEY));
};

// ---- upload processing --------------------------------------------------------------------

export const UPLOAD_MAX_BYTES = 15 * 1024 * 1024;
export const UPLOAD_MAX_WIDTH = 2560;
export const UPLOAD_MIN_WIDTH = 1920;
export const UPLOAD_MIN_HEIGHT = 1080;
const UPLOAD_QUALITY = 0.75;

export type UploadError = 'not-image' | 'too-big' | 'unreadable';

export interface ProcessedImage {
  blob: Blob;
  width: number;
  height: number;
  /** Source smaller than the recommended minimum (accepted, but it will look soft). */
  small: boolean;
  /** Mean relative luminance (0-1) of the resized image. */
  luma: number;
}

/** Validate, scale down to ≤ 2560 wide and re-encode as WebP (q 0.75). */
export const processUpload = async (file: File): Promise<ProcessedImage | UploadError> => {
  if (!file.type.startsWith('image/')) return 'not-image';
  if (file.size > UPLOAD_MAX_BYTES) return 'too-big';
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return 'unreadable';
  }
  const scale = Math.min(1, UPLOAD_MAX_WIDTH / bitmap.width);
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return 'unreadable';
  ctx.drawImage(bitmap, 0, 0, width, height);
  const small = bitmap.width < UPLOAD_MIN_WIDTH || bitmap.height < UPLOAD_MIN_HEIGHT;
  bitmap.close();
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/webp', UPLOAD_QUALITY));
  const luma = measureLuma(canvas) ?? 0.35;
  return blob ? { blob, width, height, small, luma } : 'unreadable';
};
