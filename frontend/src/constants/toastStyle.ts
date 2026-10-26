/**
 * The one toast shape (TASK-166).
 *
 * A toast is a small plain-text pill: one line, one colour, no icon. The colour already says
 * what happened (red = error, yellow = warning, green = success, gold = info), so an icon would
 * only repeat it and take the width away from the message.
 *
 * Every toast in the app — error, warning, success, info and the 24 h digest — reads this file,
 * so they all look the same. The text size comes from the type scale, never a px literal.
 */
import { TYPOGRAPHY } from './typography';

/** The pill's geometry. */
export const TOAST_PILL = {
  width: 'fit-content',
  maxWidth: 'min(92vw, 520px)',
  whiteSpace: 'nowrap' as const,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  fontSize: TYPOGRAPHY.caption.size,
  fontWeight: TYPOGRAPHY.caption.weight,
  lineHeight: TYPOGRAPHY.caption.lineHeight,
  padding: '4px 12px',
  borderRadius: '999px',
  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.2)',
};

/**
 * The pill in its status colour: a 10 % tint of that colour on the card surface, a hairline in
 * the same colour, and the text in it too.
 */
export const pillToastStyle = (color: string, surface: string) => ({
  ...TOAST_PILL,
  background: `color-mix(in srgb, ${color} 10%, ${surface})`,
  color,
  border: `1px solid ${color}`,
});
