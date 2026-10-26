import { FONT_SIZE_SCALE, TYPOGRAPHY } from '../../constants/typography';

/** The roles the docs renderer draws, keyed by markdown element. */
export type DocsTypeScale = Record<'h1' | 'h2' | 'h3' | 'h4' | 'body' | 'code' | 'table', string>;

const rem = (size: string, m: number): string => {
  const hit = /^(-?\d+(?:\.\d+)?)rem$/.exec(size);
  return hit ? `${parseFloat((parseFloat(hit[1]) * m).toFixed(4))}rem` : size;
};

/**
 * Docs reader scale, derived from the app type scale (constants/typography.ts, UI_STYLE.md 10a):
 * h1 = the pageTitle role, h2 = xl, h3 = lg, h4 and body = md, table = the tableBody role, code = the code role.
 * `compact` (the FAQ) is one step smaller on every role (0.9x). `m` multiplies the whole scale: it is the
 * user's global Size setting times the reader's own S / M / L step, so the two compose.
 */
export const docsTypeScale = (compact = false, m = 1): DocsTypeScale => {
  const k = (compact ? 0.9 : 1) * m;
  return {
    h1: rem(TYPOGRAPHY.pageTitle.size, k),
    h2: rem(FONT_SIZE_SCALE.xl, k),
    h3: rem(FONT_SIZE_SCALE.lg, k),
    h4: rem(FONT_SIZE_SCALE.md, k),
    body: rem(FONT_SIZE_SCALE.md, k),
    code: rem(TYPOGRAPHY.code.size, k),
    table: rem(TYPOGRAPHY.tableBody.size, k),
  };
};
