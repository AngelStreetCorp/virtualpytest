/**
 * UI font registry (TASK-102 G14). One family for the whole UI. `classic` is the default and needs no
 * download (Arial on Windows, Liberation Sans on Linux); Inter and Atkinson Hyperlegible are
 * self-hosted npm fonts, loaded with a dynamic import only when active (no CDN: customer LANs are offline).
 */
export type FontId = 'classic' | 'inter' | 'atkinson';
export const FONT_IDS: FontId[] = ['classic', 'inter', 'atkinson'];
export const DEFAULT_FONT: FontId = 'classic';

export const FONT_STACKS: Record<FontId, string> = {
  classic: 'Arial, "Liberation Sans", Helvetica, sans-serif',
  inter: '"Inter Variable", Inter, Arial, sans-serif',
  atkinson: '"Atkinson Hyperlegible", Arial, sans-serif',
};

export const FONT_NAMES: Record<FontId, string> = {
  classic: 'Classic',
  inter: 'Inter',
  atkinson: 'Atkinson Hyperlegible',
};

export const isFontId = (v: unknown): v is FontId => typeof v === 'string' && (FONT_IDS as string[]).includes(v);

const loaded: Partial<Record<FontId, Promise<void>>> = {};

type Face = { family: string; weight: string; url: string };

/** Bundled woff2 files (Vite hashes them); only the chosen font's module is fetched. */
const faces = async (id: Exclude<FontId, 'classic'>): Promise<Face[]> => {
  if (id === 'inter') {
    const m = await import('../assets/fonts/inter-latin-wght-normal.woff2?url');
    return [{ family: 'Inter Variable', weight: '100 900', url: m.default }];
  }
  const [a, b] = await Promise.all([
    import('../assets/fonts/atkinson-hyperlegible-latin-400-normal.woff2?url'),
    import('../assets/fonts/atkinson-hyperlegible-latin-700-normal.woff2?url'),
  ]);
  return [
    { family: 'Atkinson Hyperlegible', weight: '400', url: a.default },
    { family: 'Atkinson Hyperlegible', weight: '700', url: b.default },
  ];
};

/** Fetch and register the font files for `id` once; classic has nothing to load. */
export const loadFont = (id: FontId): Promise<void> => {
  if (id === 'classic') return Promise.resolve();
  if (!loaded[id]) {
    loaded[id] = faces(id)
      .then((list) =>
        Promise.all(
          list.map((f) =>
            new FontFace(f.family, `url(${f.url}) format('woff2')`, { weight: f.weight, display: 'swap' })
              .load()
              .then((face) => {
                document.fonts.add(face);
              }),
          ),
        ),
      )
      .then(() => undefined)
      .catch(() => {
        delete loaded[id];
      });
  }
  return loaded[id] as Promise<void>;
};

/** The font in effect: the user's own choice wins over the theme's, which wins over classic. */
export const resolveFont = (userFont: FontId | null, themeFont: FontId | undefined): FontId => userFont ?? themeFont ?? DEFAULT_FONT;
