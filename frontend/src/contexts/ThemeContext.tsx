import CssBaseline from '@mui/material/CssBaseline';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import React, { createContext, useContext, useEffect, useState } from 'react';

import { AGENT_CHAT_PALETTE, AGENT_CHAT_PALETTE_LIGHT } from '../constants/agentChatTheme';

type ThemeMode = 'light' | 'dark' | 'system';

interface ThemeContextType {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  actualMode: 'light' | 'dark'; // The actual resolved mode (system resolves to light or dark)
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

interface CustomThemeProviderProps {
  children: React.ReactNode;
}

export const CustomThemeProvider: React.FC<CustomThemeProviderProps> = ({ children }) => {
  const [mode, setMode] = useState<ThemeMode>(() => {
    // Get saved theme from localStorage or default to system
    const savedTheme = localStorage.getItem('theme-mode') as ThemeMode;
    return savedTheme || 'system';
  });

  const [systemPrefersDark, setSystemPrefersDark] = useState(
    window.matchMedia('(prefers-color-scheme: dark)').matches,
  );

  // Listen for system theme changes
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (e: MediaQueryListEvent) => {
      setSystemPrefersDark(e.matches);
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  // Save theme preference to localStorage
  useEffect(() => {
    localStorage.setItem('theme-mode', mode);
  }, [mode]);

  // Determine the actual theme mode
  const actualMode: 'light' | 'dark' =
    mode === 'system' ? (systemPrefersDark ? 'dark' : 'light') : mode;

  // Create the Material-UI theme
  // App palette (docs/agent/platform/UI_STYLE.md): gold is the primary accent in both
  // modes, so every MUI "primary" control — buttons, tabs, switches, links, dialogs,
  // menus — follows it without per-page styling. `accentText` is the readable gold for
  // text on white; info stays MUI blue, success/error/warning keep their meaning.
  const P = actualMode === 'dark' ? AGENT_CHAT_PALETTE : AGENT_CHAT_PALETTE_LIGHT;

  const theme = createTheme({
    palette: {
      mode: actualMode,
      primary: { main: P.accent, dark: P.accentHover, light: '#e6c39e', contrastText: '#1a1a1a' },
      success: { main: P.success },
      error: { main: P.error },
      warning: { main: P.warning },
      // MUI "secondary" is only ever a second categorical colour (TC/TP tags, Latest, role
      // chips): a muted palette series instead of MUI pink.
      secondary: { main: P.series[2] },
      divider: P.borderColor,
      ...(actualMode === 'dark' && {
        background: {
          default: '#0a0a0a',
          paper: '#1a1a1a',
        },
      }),
      ...(actualMode === 'light' && {
        background: {
          default: P.background,
          paper: P.surface,
        },
      }),
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          // Paint an explicit opaque background on the document's base layers.
          // Without this, regions the app doesn't paint (page margins, momentarily
          // un-composited GPU tiles) fall through to the browser's window backdrop,
          // which is pure black under `color-scheme: dark`. Tying these to the theme
          // background so a failed/empty tile falls back to #0a0a0a instead of #000,
          // and so it stays correct in light mode.
          'html, body, #root': {
            backgroundColor: actualMode === 'dark' ? '#0a0a0a' : P.background,
          },
          // Every table header, in both themes (pages inside pageSurfaceSx refine it further).
          '.MuiTableHead-root': { backgroundColor: `${P.hoverBg} !important` },
          '.MuiTableHead-root .MuiTableCell-root': { fontWeight: 600, color: `${P.textSecondary} !important` },
        },
      },
      MuiTypography: {
        styleOverrides: {
          root: {
            userSelect: 'text',
            WebkitUserSelect: 'text',
            MozUserSelect: 'text',
            msUserSelect: 'text',
          },
        },
      },
      MuiToolbar: {
        styleOverrides: {
          root: {
            '@media (max-width:899.95px)': {
              minHeight: '44px !important',
              height: '44px',
            },
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          // Hairline, no drop shadow (UI_STYLE.md "Surfaces").
          root: {
            borderRadius: 12,
            boxShadow: 'none',
            border: `1px solid ${P.borderColor}`,
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            borderRadius: 12,
            border: `1px solid ${P.borderColor}`,
            backgroundImage: 'none',
            boxShadow: actualMode === 'dark' ? '0 12px 40px rgba(0,0,0,0.6)' : '0 12px 40px rgba(0,0,0,0.15)',
          },
        },
      },
      MuiDialogTitle: {
        styleOverrides: { root: { fontSize: '1.1rem', fontWeight: 600 } },
      },
      MuiDialogActions: {
        styleOverrides: { root: { padding: '12px 24px 16px', gap: 8 } },
      },
      // Outlined fields and chips: palette hairline instead of MUI's white/grey defaults.
      // No fade on the tick: it appeared late in dark mode. Checked boxes draw the tick in white.
      MuiCheckbox: {
        defaultProps: { disableRipple: true },
        styleOverrides: {
          root: { '& .MuiSvgIcon-root': { transition: 'none' }, '&.Mui-checked': { color: P.accent } },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          notchedOutline: { borderColor: P.borderColor },
          root: { ...(actualMode === 'light' ? { backgroundColor: P.surface } : {}), '&:hover:not(.Mui-focused):not(.Mui-disabled):not(.Mui-error) .MuiOutlinedInput-notchedOutline': { borderColor: P.textMuted }, '&.Mui-disabled .MuiOutlinedInput-notchedOutline': { borderColor: P.borderColor } },
        },
      },
      MuiChip: {
        styleOverrides: {
          outlined: { '&.MuiChip-colorDefault': { borderColor: P.borderColor } },
          // Gold as text: the readable gold on white (same value in dark).
          outlinedPrimary: { color: P.accentText },
        },
      },
      // Info alerts ("nothing here yet", hints): a neutral palette card, not MUI's blue / navy box.
      MuiAlert: {
        styleOverrides: {
          standardInfo: {
            backgroundColor: P.surface,
            color: P.textPrimary,
            border: `1px solid ${P.borderColor}`,
            '& .MuiAlert-icon': { color: P.accentText },
          },
          outlinedInfo: { color: P.textPrimary, borderColor: P.borderColor, '& .MuiAlert-icon': { color: P.accentText } },
          filledInfo: { backgroundColor: P.hoverBg, color: P.textPrimary },
        },
      },
      // Switches: off = surface thumb on a hairline track (MUI's light-grey thumb glared in dark); on stays gold.
      MuiSwitch: {
        styleOverrides: {
          switchBase: { '&:not(.Mui-checked)': { color: actualMode === 'dark' ? P.textSecondary : P.surface } },
          track: { backgroundColor: P.textMuted },
        },
      },
      MuiIconButton: {
        styleOverrides: { colorPrimary: { color: P.accentText } },
      },
      MuiSvgIcon: {
        styleOverrides: { colorPrimary: { color: P.accentText } },
      },
      MuiTableCell: {
        styleOverrides: { root: { borderColor: P.borderColor, fontVariantNumeric: 'tabular-nums' } },
      },
      MuiLinearProgress: {
        styleOverrides: { colorPrimary: { backgroundColor: P.hoverBg } },
      },
      MuiMenu: {
        styleOverrides: {
          paper: { border: `1px solid ${P.borderColor}`, backgroundImage: 'none', boxShadow: P.cardShadow },
        },
      },
      MuiPopover: {
        styleOverrides: {
          paper: { border: `1px solid ${P.borderColor}`, backgroundImage: 'none' },
        },
      },
      // Autocomplete suggestion lists (tag pickers…) are a Popper, not a Menu: give them the
      // same hairline border + shadow so they don't float borderless over the page.
      MuiAutocomplete: {
        styleOverrides: {
          paper: { border: `1px solid ${P.borderColor}`, backgroundImage: 'none', boxShadow: P.cardShadow },
        },
      },
      MuiMenuItem: {
        styleOverrides: {
          root: {
            fontSize: '0.875rem',
            '&.Mui-selected': { backgroundColor: `${P.accent}26` },
            '&.Mui-selected:hover': { backgroundColor: `${P.accent}33` },
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            fontSize: '0.75rem',
            backgroundColor: actualMode === 'dark' ? '#2a2a2a' : '#1a1a1a',
            border: actualMode === 'dark' ? `1px solid ${P.borderColor}` : 'none',
          },
        },
      },
      // Tab bars sit on a card strip so they read against the warm-grey page (light) and the page (dark).
      MuiTabs: {
        styleOverrides: {
          root: { backgroundColor: P.surface, border: `1px solid ${P.borderColor}`, borderRadius: 8, paddingLeft: 4, paddingRight: 4 },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            '&.Mui-selected': { color: P.accentText, fontWeight: 600 },
          },
        },
      },
      MuiLink: {
        styleOverrides: { root: { color: P.accentText } },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            borderRadius: 8,
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            borderRadius: 0,
          },
          // The top bar is neutral in both themes (light: white with a hairline, dark: paper);
          // gold is the accent ON the bar (active item), never the bar itself.
          colorPrimary:
            actualMode === 'light'
              ? { backgroundColor: P.surface, color: P.textPrimary, boxShadow: 'none', borderBottom: `1px solid ${P.borderColor}` }
              : {},
          // Page-level bars (navigation editor header…): card surface + hairline, not MUI grey.
          colorDefault: { backgroundColor: P.surface, color: P.textPrimary, boxShadow: 'none', borderBottom: `1px solid ${P.borderColor}` },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: {
            borderRadius: 8,
            textTransform: 'none',
            fontWeight: 600,
          },
          // Gold text on white is too faint; outlined/text primary use the readable gold.
          outlinedPrimary: { color: P.accentText, borderColor: P.accent },
          // Disabled outlined buttons: palette hairline instead of MUI's white (dark) / grey (light).
          outlined: { '&.Mui-disabled': { borderColor: P.borderColor } },
          textPrimary: { color: P.accentText },
        },
      },
    },
  });

  const contextValue: ThemeContextType = {
    mode,
    setMode,
    actualMode,
  };

  return (
    <ThemeContext.Provider value={contextValue}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ThemeContext.Provider>
  );
};
