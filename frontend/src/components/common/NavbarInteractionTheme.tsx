/**
 * Scoped theme for the top bar and everything it opens (dropdowns, the Test mega-menu,
 * Server / Workspace selects, the user menu). Menus render in a portal but still read
 * this theme through React context, so the scope follows them.
 *
 * The MUI ripple is off here: inside a full-height bar item or a menu row it was clipped
 * by the element's box and looked cropped. Feedback is a flat background instead:
 * - menu rows: palette `hoverBg` on hover, a gold tint while pressed / keyboard-focused;
 * - bar items and icon buttons: see `navItemSx` (Navigation_ItemStyle.tsx).
 */
import { ThemeProvider, type Theme } from '@mui/material';
import React, { useCallback } from 'react';

import { AGENT_CHAT_PALETTE, AGENT_CHAT_PALETTE_LIGHT } from '../../constants/agentChatTheme';

export const NavbarInteractionTheme: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const scoped = useCallback((outer: Theme): Theme => {
    const P = outer.palette.mode === 'dark' ? AGENT_CHAT_PALETTE : AGENT_CHAT_PALETTE_LIGHT;
    const menuItem = outer.components?.MuiMenuItem;
    const menuItemRoot = (menuItem?.styleOverrides?.root ?? {}) as object;
    return {
      ...outer,
      components: {
        ...outer.components,
        MuiButtonBase: {
          ...outer.components?.MuiButtonBase,
          defaultProps: { ...outer.components?.MuiButtonBase?.defaultProps, disableRipple: true },
        },
        MuiIconButton: {
          ...outer.components?.MuiIconButton,
          styleOverrides: {
            ...outer.components?.MuiIconButton?.styleOverrides,
            root: {
              ...((outer.components?.MuiIconButton?.styleOverrides?.root ?? {}) as object),
              '&:active, &.Mui-focusVisible': { backgroundColor: outer.palette.action.selected },
            },
          },
        },
        MuiMenuItem: {
          ...menuItem,
          styleOverrides: {
            ...menuItem?.styleOverrides,
            root: {
              ...menuItemRoot,
              transition: 'background-color 120ms ease',
              '&:hover': { backgroundColor: P.hoverBg },
              '&:active, &.Mui-focusVisible': { backgroundColor: `${P.accent}1f` },
              '&.Mui-selected': { backgroundColor: `${P.accent}26` },
              '&.Mui-selected:hover, &.Mui-selected:active': { backgroundColor: `${P.accent}33` },
            },
          },
        },
      },
    };
  }, []);

  return <ThemeProvider theme={scoped}>{children}</ThemeProvider>;
};

export default NavbarInteractionTheme;
