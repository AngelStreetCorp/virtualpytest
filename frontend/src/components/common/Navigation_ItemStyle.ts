/**
 * Shared style of every top-bar item (plain links and dropdown triggers).
 *
 * No fixed width and no active-state font weight: a fixed minWidth padded short labels
 * like "AI" with ~30px of dead space on each side on top of the bar's space-between gap,
 * and a 400 -> 600 weight change on the active item widened it, which shifted every other
 * item sideways on each navigation. The active item is marked by colour only, so the bar
 * never reflows; equal padding leaves space-between as the only gap between labels.
 *
 * Active marker: a tab underline in gold, the app's accent (agentChatTheme) — no pill. The
 * items stretch to the full height of the top bar (App.tsx / Navigation_Bar.tsx), so the 3px
 * inset box-shadow sits on the bar's bottom edge without any layout impact. The bar is neutral
 * in both themes (dark: paper, light: white), so the active label is the readable gold of each
 * palette (`accentText`) with an `accent` underline. Hover shows a faint underline and a faint
 * wash in the text colour (white on dark, black on light); pressing deepens the wash. No ripple:
 * NavbarInteractionTheme turns it off for the bar, because a ripple clipped to a full-height
 * item looked cropped.
 */
import type { Theme } from '@mui/material';

import { AGENT_CHAT_PALETTE, AGENT_CHAT_PALETTE_LIGHT } from '../../constants/agentChatTheme';

const pal = (theme: Theme) => (theme.palette.mode === 'dark' ? AGENT_CHAT_PALETTE : AGENT_CHAT_PALETTE_LIGHT);
const wash = (theme: Theme, a: number) =>
  theme.palette.mode === 'dark' ? `rgba(255, 255, 255, ${a})` : `rgba(0, 0, 0, ${a})`;

export const navItemSx = (active: boolean) =>
  ({
    color: (theme: Theme) => (active ? pal(theme).accentText : 'inherit'),
    backgroundColor: 'transparent',
    borderRadius: '0 !important', // index.css rounds every MuiButton with !important
    boxShadow: (theme: Theme) => (active ? `inset 0 -3px 0 ${pal(theme).accent}` : 'none'),
    fontWeight: 500,
    flexShrink: 0,
    justifyContent: 'center',
    textAlign: 'center',
    textTransform: 'none',
    whiteSpace: 'nowrap',
    minWidth: 0,
    px: 1.5,
    py: 0,
    transition: 'background-color 120ms ease, box-shadow 120ms ease',
    '&:hover, &.Mui-focusVisible': (theme: Theme) => ({
      backgroundColor: wash(theme, theme.palette.mode === 'dark' ? 0.08 : 0.04),
      boxShadow: active ? undefined : `inset 0 -3px 0 ${wash(theme, 0.3)}`,
    }),
    '&:active': (theme: Theme) => ({ backgroundColor: wash(theme, theme.palette.mode === 'dark' ? 0.14 : 0.08) }),
  }) as const;
