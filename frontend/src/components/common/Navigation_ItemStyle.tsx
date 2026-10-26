/**
 * Shared style of every top-bar item (plain links and dropdown triggers).
 *
 * No fixed width and no active-state font weight: a fixed minWidth padded short labels
 * like "AI" with ~30px of dead space on each side on top of the bar's space-between gap,
 * and a 400 -> 600 weight change on the active item widened it, which shifted every other
 * item sideways on each navigation. The active item is marked by colour only, so the bar
 * never reflows; equal padding leaves space-between as the only gap between labels.
 *
 * Three preconfigured hover styles ship today, all sharing the same rules — colour-only
 * active marker, no font-weight change, no ripple, no reflow:
 *
 *   - `underline` (default): a 2 px accent underline drawn with `::after`, scaleX-animated
 *     from left to right on hover/focus (320 ms cubic-bezier(0.65, 0, 0.35, 1)).
 *   - `bracket`:    two corner brackets (top-left + bottom-right) draw inward on hover,
 *                    260 ms cubic-bezier(0.4, 0, 0.2, 1). Active items hold both
 *                    brackets in place.
 *   - `magnetic`:   the item lifts -2 px on hover with a soft inset accent ring + drop
 *                    shadow, 220 ms cubic-bezier(0.4, 0, 0.2, 1).
 *
 *   Use `navItemSx(active, hoverStyle?)` to pick from the active palette token
 *   (`Palette.navHover`, settable per theme), or pass the style explicitly to lock it.
 *   The reference render is documented in `docs/agent/platform/UIUX.md` §"Reference ·
 *   Hover patterns"; every style on this file follows the same six rules in that doc.
 *
 * No ripple: NavbarInteractionTheme turns it off for the bar, because a ripple clipped to
 * a full-height item looked cropped. The wash is a flat tint of the palette's
 * `textPrimary` (8 % alpha in dark, 4 % in light) over 220 ms; pressing deepens it to
 * 14 % / 8 %. The caret on dropdown triggers rotates with the same 220 ms motion.
 */
import { alpha, Box } from '@mui/material';
import type { Theme } from '@mui/material';
import React from 'react';

import { AGENT_CHAT_PALETTE, AGENT_CHAT_PALETTE_LIGHT } from '../../constants/agentChatTheme';
import type { NavHoverStyle } from '../../constants/themeEngine';

const pal = (theme: Theme) => (theme.palette.mode === 'dark' ? AGENT_CHAT_PALETTE : AGENT_CHAT_PALETTE_LIGHT);
const wash = (theme: Theme, a: number) => alpha(pal(theme).textPrimary, a);

const COMMON = {
  backgroundColor: 'transparent',
  borderRadius: '0 !important' as const, // index.css rounds every MuiButton with !important
  fontWeight: 500,
  // BUG-0773: the bar has to survive a right-hand slot that grows (the "N online" chip)
  // and locales whose labels are longer than English. The items therefore shrink and
  // their label ellipsizes (see `navLabelSx`) instead of the row painting over the
  // slot on its right. `minWidth: 0` lets the item go below its content width.
  flexShrink: 1,
  justifyContent: 'center',
  textAlign: 'center',
  textTransform: 'none',
  whiteSpace: 'nowrap',
  minWidth: 0,
  // The caret of a dropdown trigger stays whole: only the label may be cut.
  '& .MuiButton-endIcon': { flexShrink: 0 },
  // MuiButton's default `:hover` paints `palette.action.hover` — a warm tint in
  // this theme (the brown wash on the Device tab in the screenshot). Force it
  // transparent on every state; the affordance is the underline only.
  '&:hover, &.Mui-focusVisible, &:active': { backgroundColor: 'transparent !important' },
  // BUG-0773: 6 px per side, not 12. Ten items x 12 px was 240 px of pure padding —
  // more than the "N online" chip needs — and in French/German the row had no slack
  // left, so the chip landed on the Settings label. The bar keeps its `space-between`
  // spread, so the labels stay evenly spaced in English.
  px: 0.75,
  py: 0,
  position: 'relative' as const,
};

/**
 * The label of a top-bar item.
 *
 * A block-level span so `text-overflow: ellipsis` can cut it: when the bar is too
 * narrow for the whole label (BUG-0773 — French "Paramètres" under the "N online"
 * chip, German "Einstellungen"), the item shrinks and the label shows an ellipsis
 * instead of the row spilling over the slot on its right.
 */
export const navLabelSx = {
  display: 'block',
  minWidth: 0,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
} as const;

/**
 * The label of a top-bar item, with the full text kept in a native tooltip when the
 * bar is too narrow and the label has to be cut (BUG-0773). On a 1280 px screen the
 * German bar has no room for every label; the item still has to say what it is.
 */
export const NavLabel: React.FC<{ text: string }> = ({ text }) => {
  const ref = React.useRef<HTMLSpanElement | null>(null);
  const [truncated, setTruncated] = React.useState(false);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const check = () => setTruncated(el.scrollWidth > el.clientWidth + 1);
    check();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text]);

  return (
    <Box component="span" ref={ref} sx={navLabelSx} title={truncated ? text : undefined}>
      {text}
    </Box>
  );
};

const COMMON_TRANSITION =
  'background-color 220ms cubic-bezier(0.4, 0, 0.2, 1), ' +
  'color 220ms cubic-bezier(0.4, 0, 0.2, 1), ' +
  'transform 220ms cubic-bezier(0.4, 0, 0.2, 1), ' +
  'box-shadow 220ms ease';

const COMMON_PRESS = (theme: Theme) => ({
  backgroundColor: wash(theme, theme.palette.mode === 'dark' ? 0.14 : 0.08),
});

/** Default hover style — underline grow (L → R). See UIUX.md for the reference render.
 *  The hover is the line only: no background wash, no label-colour change. The bar reads
 *  as flat; the motion is the affordance. Pressing deepens the line to full alpha accent. */
export const navItemUnderlineSx = (active: boolean) => ({
  ...COMMON,
  color: (theme: Theme) => (active ? pal(theme).accentText : 'inherit'),
  boxShadow: 'none',
  transition: COMMON_TRANSITION,
  '&::after': {
    content: '""',
    position: 'absolute',
    left: 6,
    right: 6,
    bottom: 8,
    height: 2,
    borderRadius: 1,
    backgroundColor: (theme: Theme) =>
      active ? pal(theme).accent : alpha(pal(theme).accent, 0.55),
    transform: active ? 'scaleX(1)' : 'scaleX(0)',
    transformOrigin: 'left center',
    transition: 'transform 320ms cubic-bezier(0.65, 0, 0.35, 1), background-color 220ms ease',
  },
  '&:hover::after, &.Mui-focusVisible::after': active
    ? {}
    : { transform: 'scaleX(1)' },
  '&:active::after': active ? {} : { backgroundColor: (theme: Theme) => pal(theme).accent },
});

/** Bracket-frame hover — two corner brackets draw inward. Same active marker, no underline. */
export const navItemBracketSx = (active: boolean) => ({
  ...COMMON,
  color: (theme: Theme) => (active ? pal(theme).accentText : 'inherit'),
  boxShadow: 'none',
  transition: COMMON_TRANSITION,
  // Two pseudo-elements: top-left and bottom-right corners. Static base styles only —
  // any per-state override goes through the active/hover keys so the type stays uniform.
  '&::before, &::after': {
    content: '""',
    position: 'absolute',
    width: 10,
    height: 10,
    border: '1.5px solid',
    borderColor: (theme: Theme) => pal(theme).accent,
    opacity: active ? 1 : 0,
    transition:
      'opacity 220ms ease, transform 260ms cubic-bezier(0.4, 0, 0.2, 1)',
  },
  '&::before': {
    top: 10 ,
    left: 6,
    borderRight: 0,
    borderBottom: 0,
    transform: active ? 'translate(0, 0)' : 'translate(4px, -4px)',
  },
  '&::after': {
    bottom: 8,
    right: 6,
    borderLeft: 0,
    borderTop: 0,
    transform: active ? 'translate(0, 0)' : 'translate(-4px, 4px)',
  },
  '&:hover, &.Mui-focusVisible': (theme: Theme) => ({
    color: pal(theme).accent,
  }),
  '&:hover::before, &:hover::after, &.Mui-focusVisible::before, &.Mui-focusVisible::after':
    {
      opacity: 1,
      transform: 'translate(0, 0)',
    },
  '&:active': COMMON_PRESS,
});

/** Magnetic-lift hover — translateY(-2 px) + soft inset ring + drop shadow.
 *
 *  The bar's parent uses `alignItems: 'stretch'`, which would otherwise force
 *  this button to fill the AppBar's full 64 px height and leave ~20 px of empty
 *  space above and below the label (a tall magenta rectangle with the word
 *  floating in the middle). The combination below cancels that:
 *    - `alignSelf: 'center'` opts out of `alignItems: 'stretch'` so the button
 *      sizes to its content + px padding;
 *    - `minHeight: 'auto'` overrides MuiButton's 36 px medium-size minimum, the
 *      second source of dead vertical space;
 *    - `py: 0` removes the vertical padding (the label's own line-height
 *      provides the only vertical breathing room — same as the underline and
 *      bracket styles).
 *  Result: the ring hugs the text top-to-bottom, hover lift and shadow
 *  unchanged. */
export const navItemMagneticSx = (active: boolean) => ({
  ...COMMON,
  // index.css rounds every MuiButton with !important; this 8 px wins there for the magnet.
  borderRadius: '8px !important' as const,
  color: (theme: Theme) => (active ? pal(theme).accentText : 'inherit'),
  boxShadow: 'none',
  transition: COMMON_TRANSITION,
  px: 0.75,         // same trim as COMMON (BUG-0773): the magnetic style needs less horizontal breathing room
  py: 0,             // no vertical padding; let the label's line-height set the box height
  alignSelf: 'center', // opt out of `alignItems: 'stretch'` on the nav row
  minHeight: 'auto',   // override MuiButton's 36 px default, the second source of dead space
  '&:hover, &.Mui-focusVisible': (theme: Theme) => ({
    color: pal(theme).accent,
    transform: 'translateY(-2px)',
    boxShadow:
      '0 4px 12px rgba(0,0,0,0.35), inset 0 0 0 1px ' +
      alpha(pal(theme).accent, 0.18),
  }),
  // Active items: same lift from the start, no hover needed.
  ...(active
    ? {
        color: (theme: Theme) => pal(theme).accentText,
        transform: 'translateY(-2px)',
        boxShadow: (theme: Theme) =>
          '0 4px 12px rgba(0,0,0,0.35), inset 0 0 0 1px ' +
          alpha(pal(theme).accent, 0.35),
      }
    : {}),
  '&:active': (theme: Theme) => ({
    transform: 'translateY(-1px)',
    boxShadow:
      '0 2px 6px rgba(0,0,0,0.3), inset 0 0 0 1px ' +
      alpha(pal(theme).accent, 0.22),
  }),
});

/** Selector — picks the preconfigured style for the active palette, or one passed in.
 *  All three implementations are theme-reactive through the palette module. */
export const navItemSx = (active: boolean, hoverStyle?: NavHoverStyle) => {
  const style: NavHoverStyle = hoverStyle ?? AGENT_CHAT_PALETTE.navHover;
  switch (style) {
    case 'bracket':
      return navItemBracketSx(active);
    case 'magnetic':
      return navItemMagneticSx(active);
    case 'underline':
    default:
      return navItemUnderlineSx(active);
  }
};