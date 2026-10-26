/**
 * Sticky geometry of the docs rails (left nav, right "On this page"), measured in the browser (TASK-124 r3).
 *
 * The app shell is: a static top bar (64 px), then ONE scrolling column (App.tsx, `overflowY: auto`) that
 * starts right under it and ends above the 20 px footer. A sticky `top` is measured from that scroller's
 * top edge, not from the window, so the gap under the navbar is just DOCS_STICKY_TOP. (Writing navbar + 8 = 72
 * here left the rails 72 px below the scroller top: 8 px lower than the card at rest, with a gap while scrolling.)
 * At rest a rail sits at its natural spot, level with the reader card's top edge; scrolled, it holds
 * DOCS_STICKY_TOP under the navbar and runs down to 16 px above the footer.
 */
export const DOCS_STICKY_TOP = 8;
/** Fixed shell height around the scroller: 64 px top bar + 20 px footer (measured at 1440 and 1100 wide). */
export const DOCS_SHELL_CHROME_PX = 84;
export const DOCS_RAIL_BOTTOM_GAP = 16;

/** `position: sticky` styles shared by both rails: they share one top edge and one bottom edge. */
export const docsRailStickySx = {
  position: 'sticky',
  top: DOCS_STICKY_TOP,
  alignSelf: 'start',
  maxHeight: `calc(100vh - ${DOCS_SHELL_CHROME_PX}px - ${DOCS_STICKY_TOP}px - ${DOCS_RAIL_BOTTOM_GAP}px)`,
} as const;

/**
 * Reading measure of body text (paragraphs, lists, headings): about 100 characters per line. The card itself
 * spans the whole column; code blocks, tables and images may use all of it. The text column is centred when a
 * rail is collapsed (the card is then wider than the measure) and left-aligned otherwise.
 * It is one rem width derived from the body size, NOT `100ch` on each element: `ch` follows the element's own
 * font size, so a heading would get a wider column than a paragraph and the left edges would not line up.
 */
export const DOCS_MEASURE_CHARS = 100;
/** Average glyph width of the UI sans-serif, in em: ~0.55 (so 100 characters of 0.875rem text = 48 rem). */
const AVG_GLYPH_EM = 0.55;
export const docsMeasure = (bodyRem: number): string => `${(DOCS_MEASURE_CHARS * AVG_GLYPH_EM * bodyRem).toFixed(2)}rem`;
/** Height of the reader card's header bar (one row, constant in every rail state). */
export const DOCS_BAR_HEIGHT = 44;
