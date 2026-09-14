import CssBaseline from '@mui/material/CssBaseline';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import React, { createContext, useContext, useEffect, useState } from 'react';

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
  const theme = createTheme({
    palette: {
      mode: actualMode,
      ...(actualMode === 'dark' && {
        background: {
          default: '#0a0a0a',
          paper: '#1a1a1a',
        },
        primary: {
          main: '#90caf9',
        },
        secondary: {
          main: '#f48fb1',
        },
      }),
      ...(actualMode === 'light' && {
        background: {
          default: '#fafafa',
          paper: '#ffffff',
        },
        primary: {
          main: '#1976d2',
        },
        secondary: {
          main: '#dc004e',
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
            backgroundColor: actualMode === 'dark' ? '#0a0a0a' : '#fafafa',
          },
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
          root: {
            borderRadius: 12,
            boxShadow:
              actualMode === 'dark'
                ? '0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -1px rgba(0, 0, 0, 0.2)'
                : '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
          },
        },
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
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            textTransform: 'none',
            fontWeight: 600,
          },
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
