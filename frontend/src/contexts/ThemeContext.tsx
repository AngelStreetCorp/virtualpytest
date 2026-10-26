import CssBaseline from '@mui/material/CssBaseline';
import { ThemeProvider, alpha, createTheme } from '@mui/material/styles';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import BackgroundLayer from '../components/common/BackgroundLayer';
import { AGENT_CHAT_PALETTE, AGENT_CHAT_PALETTE_LIGHT, setActivePalettes } from '../constants/agentChatTheme';
import {
  BG_CUSTOM,
  BackgroundSettings,
  ModeBackground,
  BG_NONE,
  TINT_ORIGINAL,
  deleteThemeImage,
  findPreset,
  isLuma,
  loadBackgrounds,
  loadThemeImage,
  measureBlobLuma,
  presetUrl,
  saveBackgrounds,
  saveThemeImage,
  tintColour,
  tintFilter,
  tintOverlay,
  veilAlpha,
} from '../constants/themeBackgrounds';
import { Palette, ThemeDef, derivePalettes, parseTheme, readableOn } from '../constants/themeEngine';
import {
  CUSTOM_ID,
  CustomThemeInput,
  listThemes,
  loadCustom,
  loadProvided,
  loadSelected,
  loadUserFont,
  loadUserNavHover,
  loadUserSize,
  resolveSize,
  saveUserFont,
  saveUserNavHover,
  saveUserSize,
  resolveTheme,
  saveCustom,
  saveProvided,
  saveSelected,
  type UserNavHover,
} from '../constants/themeStore';
import { FONT_STACKS, FontId, loadFont, resolveFont } from '../constants/themeFonts';
import {
  TYPOGRAPHY,
  SizeId,
  DEFAULT_SIZE,
  SIZE_SCALE,
  remToPx,
  slotStyle,
  TypographyRole,
} from '../constants/typography';
import { REDUCE_MOTION_KEY, loadFlag, loadMenuIconColour, saveFlag, saveMenuIconColour } from '../constants/uiPrefs';
import { buildServerUrl } from '../utils/buildUrlUtils';

type ThemeMode = 'light' | 'dark' | 'system';

interface ThemeContextType {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  actualMode: 'light' | 'dark'; // The actual resolved mode (system resolves to light or dark)
  /** Colour themes (TASK-102): gold, the install's provided themes, the user's own. */
  colourThemes: ThemeDef[];
  activeColourThemeId: string;
  selectColourTheme: (id: string) => void;
  customColourTheme: CustomThemeInput | null;
  /** Save the user's one theme and switch to it. */
  saveCustomColourTheme: (c: CustomThemeInput) => void;
  deleteCustomColourTheme: () => void;
  refreshColourThemes: () => void;
  /** UI font in effect (TASK-102 G14) and the user's own choice (null = the theme's font). */
  font: FontId;
  userFont: FontId | null;
  setUserFont: (f: FontId | null) => void;
  /** Per-user navbar hover style. Independent of the theme — UI choice, not a colour. */
  userNavHover: UserNavHover;
  setUserNavHover: (s: UserNavHover) => void;
  /** TASK-100: UI size scale (sm/md/lg). User choice wins over the theme's. */
  size: SizeId;
  userSize: SizeId | null;
  setUserSize: (s: SizeId | null) => void;
  /** 1.0 = the raw role size; sm/md/lg maps to 0.875/1/1.125 via SIZE_SCALE. */
  sizeMultiplier: number;
  /** The user's Reduce motion switch, and whether motion is off in effect (the OS setting always wins). */
  reduceMotion: boolean;
  setReduceMotion: (on: boolean) => void;
  motionReduced: boolean;
  /** TASK-136: background settings per mode; `actualMode` picks the one in effect. */
  backgrounds: BackgroundSettings;
  /** Replace the settings (applied live and stored). */
  setBackgrounds: (b: BackgroundSettings) => void;
  /** Change the current mode's settings. */
  updateModeBackground: (patch: Partial<ModeBackground>) => void;
  /** The user's one image in memory (a dialog draft until committed), and its object URL. */
  customImage: Blob | null;
  customImageUrl: string | null;
  setCustomImage: (blob: Blob | null) => void;
  /** Write the in-memory image to IndexedDB (or delete it when there is none). False = not stored. */
  commitCustomImage: () => Promise<boolean>;
  /** Navbar menu icon colour pref (`default` | `theme` | `series:N` | #hex) and its colour (undefined = default). */
  menuIconColour: string;
  setMenuIconColour: (v: string) => void;
  menuIconColourResolved: string | undefined;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

/** `#rrggbb` + alpha as `#rrggbbaa` (so `${colour}xx` suffix users of the palette still work); other formats via MUI alpha. */
const hexAlpha = (colour: string, a: number): string =>
  /^#[0-9a-fA-F]{6}$/.test(colour)
    ? colour + Math.round(Math.min(1, Math.max(0, a)) * 255).toString(16).padStart(2, '0')
    : alpha(colour, a);

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

  const [provided, setProvided] = useState<ThemeDef[]>(loadProvided);
  const [custom, setCustom] = useState<CustomThemeInput | null>(loadCustom);
  const [selectedId, setSelectedId] = useState<string | null>(loadSelected);

  const colourThemes = useMemo(() => listThemes(provided, custom), [provided, custom]);
  const activeColourTheme = useMemo(() => resolveTheme(colourThemes, selectedId), [colourThemes, selectedId]);

  const refreshColourThemes = useCallback(() => {
    fetch(buildServerUrl('/server/themes'))
      .then((res) => (res.ok ? res.json() : null))
      .then((body) => {
        if (!body || !Array.isArray(body.themes)) return;
        const list = (body.themes as unknown[]).map(parseTheme).filter((t): t is ThemeDef => t !== null);
        setProvided(list);
        saveProvided(list);
      })
      .catch(() => undefined); // signed out or offline: keep what we have
  }, []);

  useEffect(() => {
    refreshColourThemes();
  }, [refreshColourThemes]);

  const selectColourTheme = useCallback((id: string) => {
    setSelectedId(id);
    saveSelected(id);
  }, []);

  const saveCustomColourTheme = useCallback((c: CustomThemeInput) => {
    setCustom(c);
    saveCustom(c);
    setSelectedId(CUSTOM_ID);
    saveSelected(CUSTOM_ID);
  }, []);

  const deleteCustomColourTheme = useCallback(() => {
    setCustom(null);
    saveCustom(null);
  }, []);

  const [userFont, setUserFontState] = useState<FontId | null>(loadUserFont);
  const setUserFont = useCallback((f: FontId | null) => {
    setUserFontState(f);
    saveUserFont(f);
  }, []);
  const [userNavHover, setUserNavHoverState] = useState<UserNavHover>(loadUserNavHover);
  const setUserNavHover = useCallback((s: UserNavHover) => {
    setUserNavHoverState(s);
    saveUserNavHover(s);
  }, []);
  const [userSize, setUserSizeState] = useState<SizeId | null>(loadUserSize);
  const setUserSize = useCallback((s: SizeId | null) => {
    setUserSizeState(s);
    saveUserSize(s ?? DEFAULT_SIZE);
  }, []);
  const [reduceMotion, setReduceMotionState] = useState<boolean>(() => loadFlag(REDUCE_MOTION_KEY));
  const setReduceMotion = useCallback((on: boolean) => {
    setReduceMotionState(on);
    saveFlag(REDUCE_MOTION_KEY, on);
  }, []);
  const [osReducesMotion, setOsReducesMotion] = useState(
    window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = (e: MediaQueryListEvent) => setOsReducesMotion(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  const motionReduced = reduceMotion || osReducesMotion;
  const [menuIconColour, setMenuIconColourState] = useState<string>(loadMenuIconColour);
  const setMenuIconColour = useCallback((v: string) => {
    setMenuIconColourState(v);
    saveMenuIconColour(v);
  }, []);
  const font = resolveFont(userFont, activeColourTheme.font);
  const size = resolveSize(userSize, activeColourTheme.uiOptions?.size);
  const sizeMultiplier = SIZE_SCALE[size];
  useEffect(() => {
    document.documentElement.style.setProperty('--app-font', FONT_STACKS[font]);
    document.documentElement.style.setProperty('--app-font-scale', String(sizeMultiplier));
    loadFont(font); // the browser swaps the face in when the lazy chunk arrives
  }, [font, sizeMultiplier]);

  const palettes = useMemo(() => derivePalettes(activeColourTheme), [activeColourTheme]);

  const [backgrounds, setBackgroundsState] = useState<BackgroundSettings>(loadBackgrounds);
  const setBackgrounds = useCallback((b: BackgroundSettings) => {
    setBackgroundsState(b);
    saveBackgrounds(b);
  }, []);
  const [customImage, setCustomImage] = useState<Blob | null>(null);
  useEffect(() => {
    loadThemeImage().then(setCustomImage);
  }, []);
  const customImageUrl = useMemo(() => (customImage ? URL.createObjectURL(customImage) : null), [customImage]);
  useEffect(() => () => {
    if (customImageUrl) URL.revokeObjectURL(customImageUrl);
  }, [customImageUrl]);
  const commitCustomImage = useCallback(async () => {
    if (customImage) return saveThemeImage(customImage);
    await deleteThemeImage();
    return true;
  }, [customImage]);
  // An image stored without its brightness: measure it once.
  useEffect(() => {
    if (!customImage || isLuma(backgrounds.customLuma)) return;
    measureBlobLuma(customImage).then((luma) => {
      if (luma === null) return;
      setBackgroundsState((prev) => {
        const next = { ...prev, customLuma: luma };
        saveBackgrounds(next);
        return next;
      });
    });
  }, [customImage, backgrounds.customLuma]);

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

  const updateModeBackground = useCallback(
    (patch: Partial<ModeBackground>) => {
      // A newly picked image that is not painted in gold starts in its own colours; the tint is one click away.
      const picked = patch.img !== undefined && patch.tint === undefined ? findPreset(patch.img) : undefined;
      const fullPatch: Partial<ModeBackground> =
        patch.img !== undefined && patch.img !== BG_NONE && patch.tint === undefined && (patch.img === BG_CUSTOM || picked?.baseHue === null)
          ? { ...patch, tint: TINT_ORIGINAL }
          : patch;
      setBackgroundsState((prev) => {
        const next = { ...prev, [actualMode]: { ...prev[actualMode], ...fullPatch } };
        saveBackgrounds(next);
        return next;
      });
    },
    [actualMode],
  );

  // Background image in effect for this mode; the user's image waits for its blob (no flash of nothing).
  const modeBg = backgrounds[actualMode];
  const bgPreset = findPreset(modeBg.img);
  const bgUrl = modeBg.img === BG_CUSTOM ? customImageUrl : bgPreset ? presetUrl(bgPreset.id) : null;
  const bgOn = bgUrl !== null;
  const cardAlpha = 1 - modeBg.cardTransparency / 100;
  // With an image on, every card surface a page paints from the palette (P.surface / P.sidebarBg) follows the
  // card transparency too, not only MUI Paper; the opaque colours stay in `*Solid` for nodes, overlays and toasts.
  const cardPalette = (p: Palette): Palette =>
    bgOn ? { ...p, surfaceSolid: p.surface, sidebarBgSolid: p.sidebarBg, surface: hexAlpha(p.surface, cardAlpha), sidebarBg: hexAlpha(p.sidebarBg, cardAlpha) } : { ...p, surfaceSolid: p.surface, sidebarBgSolid: p.sidebarBg };

  // Create the Material-UI theme
  // App palette (docs/agent/platform/UI_STYLE.md): gold is the primary accent in both
  // modes, so every MUI "primary" control — buttons, tabs, switches, links, dialogs,
  // menus — follows it without per-page styling. `accentText` is the readable gold for
  // text on white; info stays MUI blue, success/error/warning keep their meaning.
  // User's navbar hover style is a per-user UI choice and wins over the theme's `navHover`
  // (which is the default a theme may declare via `uiOptions.navHover`).
  // Update the live palettes before anything below reads them (non-React colour constants too).
  setActivePalettes({
    ...palettes,
    dark: { ...(actualMode === 'dark' ? cardPalette(palettes.dark) : palettes.dark), navHover: userNavHover },
    light: { ...(actualMode === 'light' ? cardPalette(palettes.light) : palettes.light), navHover: userNavHover },
  });

  // When the user flips their navHover after first paint, patch the active palette in
  // place so any navItemSx() call (which reads AGENT_CHAT_PALETTE.navHover) sees it.
  useEffect(() => {
    Object.assign(AGENT_CHAT_PALETTE, { navHover: userNavHover });
    Object.assign(AGENT_CHAT_PALETTE_LIGHT, { navHover: userNavHover });
  }, [userNavHover]);
  const P = actualMode === 'dark' ? palettes.dark : palettes.light;
  const menuIconColourResolved =
    menuIconColour === 'theme'
      ? P.accentText
      : menuIconColour.startsWith('series:')
        ? P.series[Number(menuIconColour.slice(7))]
        : menuIconColour.startsWith('#')
          ? menuIconColour
          : undefined;

  const paperColour = actualMode === 'dark' ? P.paperBackground : P.surface;
  const blurSx = { backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' };

  const theme = createTheme({
    // Reduce motion: MUI transitions (fades, collapses, ripples) become instant.
    ...(motionReduced && { transitions: { create: () => 'none' } }),
    typography: {
      fontFamily: FONT_STACKS[font],
      // MUI htmlFontSize is the rem root (defaults to 14). MUI's h1-h6 / body1-2 / subtitle1-2 /
      // caption / overline / button all translate into rem against this. Override each from
      // the role table in constants/typography.ts so a future size tweak is a one-line edit
      // there, not a sweep through MUI variant consumers.
      htmlFontSize: 16,
      fontSize: remToPx(TYPOGRAPHY.body.size), // 13 px at multiplier 1, matches body.size
      h1:       { fontSize: TYPOGRAPHY.pageTitle.size,     fontWeight: TYPOGRAPHY.pageTitle.weight,     lineHeight: TYPOGRAPHY.pageTitle.lineHeight },
      h2:       { fontSize: TYPOGRAPHY.kpiValue.size,      fontWeight: TYPOGRAPHY.kpiValue.weight,      lineHeight: TYPOGRAPHY.kpiValue.lineHeight },
      h3:       { fontSize: TYPOGRAPHY.pageTitle.size,                       fontWeight: 600, lineHeight: 1.2 },
      h4:       { fontSize: TYPOGRAPHY.sectionTitle.size,  fontWeight: TYPOGRAPHY.sectionTitle.weight,  lineHeight: TYPOGRAPHY.sectionTitle.lineHeight },
      h5:       { fontSize: TYPOGRAPHY.sectionTitle.size,  fontWeight: TYPOGRAPHY.sectionTitle.weight,  lineHeight: TYPOGRAPHY.sectionTitle.lineHeight },
      h6:       { fontSize: TYPOGRAPHY.cardTitle.size,     fontWeight: TYPOGRAPHY.cardTitle.weight,     lineHeight: TYPOGRAPHY.cardTitle.lineHeight },
      subtitle1:{ fontSize: TYPOGRAPHY.pageSubtitle.size,  fontWeight: TYPOGRAPHY.pageSubtitle.weight,  lineHeight: TYPOGRAPHY.pageSubtitle.lineHeight },
      subtitle2:{ fontSize: TYPOGRAPHY.buttonLabel.size,   fontWeight: TYPOGRAPHY.buttonLabel.weight,   lineHeight: TYPOGRAPHY.buttonLabel.lineHeight },
      body1:    { fontSize: TYPOGRAPHY.body.size,           lineHeight: TYPOGRAPHY.body.lineHeight },
      body2:    { fontSize: TYPOGRAPHY.body.size,           lineHeight: TYPOGRAPHY.body.lineHeight },
      caption:  { fontSize: TYPOGRAPHY.caption.size,        lineHeight: TYPOGRAPHY.caption.lineHeight },
      overline: { fontSize: TYPOGRAPHY.microMeta.size,      fontWeight: TYPOGRAPHY.microMeta.weight,     letterSpacing: '0.08em' },
      button:   { fontSize: TYPOGRAPHY.buttonLabel.size,   fontWeight: TYPOGRAPHY.buttonLabel.weight,   textTransform: 'none' },
    },
    palette: {
      mode: actualMode,
      primary: { main: P.accent, dark: P.accentHover, light: P.accentLight, contrastText: readableOn(P.accent) },
      success: { main: P.success },
      error: { main: P.error },
      warning: { main: P.warning },
      // MUI "secondary" is only ever a second categorical colour (TC/TP tags, Latest, role
      // chips): a muted palette series instead of MUI pink.
      secondary: { main: P.series[2] },
      divider: P.borderColor,
      ...(actualMode === 'dark' && {
        background: {
          // Page and paper bases come from the palette (gold keeps its near-black base there).
          default: P.pageBackground,
          paper: P.paperBackground,
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
            backgroundColor: P.pageBackground,
          },
          // The background layer sits between <html>'s colour and the app (AppBackground).
          ...(bgOn && { 'body, #root': { backgroundColor: 'transparent' } }),
          ...(motionReduced && {
            '*, *::before, *::after': {
              animationDuration: '0.001ms !important',
              animationIterationCount: '1 !important',
              transitionDuration: '0.001ms !important',
              scrollBehavior: 'auto !important',
            },
            // A spinner is the "still working" signal, not decoration: frozen, it looks like a hang.
            // MUI's root rotation and its circle dash both run 1.4 s.
            '.MuiCircularProgress-root, .MuiCircularProgress-root *': {
              animationDuration: '1.4s !important',
              animationIterationCount: 'infinite !important',
            },
          }),
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
            boxShadow: P.dialogShadow,
          },
        },
      },
      MuiDialogTitle: {
        styleOverrides: { root: { fontSize: TYPOGRAPHY.dialogTitle.size, fontWeight: TYPOGRAPHY.dialogTitle.weight, lineHeight: TYPOGRAPHY.dialogTitle.lineHeight } },
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
      // Dropdown value and resting label are vertically centred in the field, whatever its height.
      MuiSelect: {
        styleOverrides: {
          select: { display: 'flex', alignItems: 'center', boxSizing: 'border-box', height: '100%' },
        },
      },
      MuiFormControl: {
        styleOverrides: {
          root: { '&:has(.MuiSelect-select) > .MuiInputLabel-outlined:not(.MuiInputLabel-shrink)': { top: '50%', transform: 'translate(14px, -50%)' } },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          notchedOutline: { borderColor: P.borderColor },
          // P.inputBg in BOTH modes — light sets it (was surface/white), dark now binds too
          // (was unset, which fell back to MUI's blue default). The token stays one notch lighter
          // than surface in dark (per UI_STYLE.md "inset fields").
          root: {
            backgroundColor: P.inputBg,
            // Browser-remembered email/password (-webkit-autofill) would otherwise paint the
            // input blue and gold-fill the text; box-shadow at field height keeps the autofill
            // background on-palette and rewrites text colour through -webkit-text-fill-color.
            '& input:-webkit-autofill': {
              WebkitBoxShadow: `0 0 0 100px ${P.inputBg} inset`,
              WebkitTextFillColor: P.textPrimary,
              caretColor: P.textPrimary,
            },
            '&:hover:not(.Mui-focused):not(.Mui-disabled):not(.Mui-error) .MuiOutlinedInput-notchedOutline': { borderColor: P.textMuted },
            '&.Mui-disabled .MuiOutlinedInput-notchedOutline': { borderColor: P.borderColor },
          },
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
            '& .MuiAlert-icon': { color: P.textSecondary },
          },
          outlinedInfo: { color: P.textPrimary, borderColor: P.borderColor, '& .MuiAlert-icon': { color: P.textSecondary } },
          filledInfo: { backgroundColor: P.hoverBg, color: P.textPrimary },
          // Status severities use the fixed palette status colours, not MUI defaults.
          standardSuccess: { color: P.textPrimary, backgroundColor: P.surface, border: `1px solid ${P.success}`, '& .MuiAlert-icon': { color: P.success } },
          outlinedSuccess: { color: P.textPrimary, borderColor: P.success, '& .MuiAlert-icon': { color: P.success } },
          standardError: { color: P.textPrimary, backgroundColor: P.surface, border: `1px solid ${P.error}`, '& .MuiAlert-icon': { color: P.error } },
          outlinedError: { color: P.textPrimary, borderColor: P.error, '& .MuiAlert-icon': { color: P.error } },
          standardWarning: { color: P.textPrimary, backgroundColor: P.surface, border: `1px solid ${P.warning}`, '& .MuiAlert-icon': { color: P.warning } },
          outlinedWarning: { color: P.textPrimary, borderColor: P.warning, '& .MuiAlert-icon': { color: P.warning } },
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
            fontSize: TYPOGRAPHY.menuItem.size,
            lineHeight: TYPOGRAPHY.menuItem.lineHeight,
            '&.Mui-selected': { backgroundColor: `${P.accent}26` },
            '&.Mui-selected:hover': { backgroundColor: `${P.accent}33` },
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            fontSize: TYPOGRAPHY.tooltip.size,
            lineHeight: TYPOGRAPHY.tooltip.lineHeight,
            backgroundColor: P.tooltipBg,
            border: actualMode === 'dark' ? `1px solid ${P.borderColor}` : 'none',
          },
        },
      },
      // Tab bars sit on a card strip so they read against the warm-grey page (light) and the page (dark).
      MuiTabs: {
        styleOverrides: {
          root: { backgroundColor: bgOn ? alpha(P.surface, cardAlpha) : P.surface, border: `1px solid ${P.borderColor}`, borderRadius: 8, paddingLeft: 4, paddingRight: 4 },
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
            // Background image on: every paper at the user's card transparency (no blur: cheap behind
            // live video tiles); dialogs stay opaque; menus, popovers and the top bar blur what is under them.
            ...(bgOn && {
              backgroundColor: alpha(paperColour, cardAlpha),
              '&.MuiDialog-paper': { backgroundColor: paperColour },
              '&.MuiPopover-paper, &.MuiAutocomplete-paper': { backgroundColor: alpha(paperColour, 0.78), ...blurSx },
              '&.MuiAppBar-colorPrimary': { backgroundColor: alpha(P.pageBackground, 0.55), ...blurSx },
            }),
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            borderRadius: 0,
            // The top bar is a single surface that matches the page background — no
            // shadow, no hairline that turns into a "bloc" between the bar and the
            // page, no lighter chip behind each button. The bar IS the page's
            // background; the active item is colour + underline, nothing else.
            backgroundImage: 'none',
            // !important fights MuiPaper's elevation shadow which would otherwise
            // paint at elevation>=1 even when the prop is set to 0 (MUI's Paper
            // hook recomputes shadow from the prop, but on the AppBar a
            // higher-specificity rule from index.css or the paper component itself
            // can still win).
            boxShadow: 'none !important',
            backgroundColor: P.pageBackground,
            color: P.textPrimary,
          },
          // Page-level bars (navigation editor header…): card surface + hairline, not MUI grey.
          colorDefault: { backgroundColor: P.surface, color: P.textPrimary, boxShadow: 'none', borderBottom: `1px solid ${P.borderColor}` },
        },
      },
      // SELECTED role by default: a plain <ToggleButton selected> / ToggleButtonGroup (no MUI blue).
      MuiToggleButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            color: P.neutralText,
            borderColor: P.neutralBorder,
            '&.Mui-selected, &.Mui-selected:hover': {
              backgroundColor: P.selectedBg,
              color: P.selectedText,
              borderColor: P.selectedBorder,
            },
          },
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
    colourThemes,
    activeColourThemeId: activeColourTheme.id,
    selectColourTheme,
    customColourTheme: custom,
    saveCustomColourTheme,
    deleteCustomColourTheme,
    refreshColourThemes,
    font,
    userFont,
    setUserFont,
    userNavHover,
    setUserNavHover,
    size,
    userSize,
    setUserSize,
    sizeMultiplier,
    reduceMotion,
    setReduceMotion,
    motionReduced,
    backgrounds,
    setBackgrounds,
    updateModeBackground,
    customImage,
    customImageUrl,
    setCustomImage,
    commitCustomImage,
    menuIconColour,
    setMenuIconColour,
    menuIconColourResolved,
  };

  return (
    <ThemeContext.Provider value={contextValue}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {bgOn && (
          <BackgroundLayer
            fixed
            url={bgUrl}
            filter={tintFilter(bgPreset, tintColour(modeBg.tint, P.accent))}
            overlay={tintOverlay(bgPreset, tintColour(modeBg.tint, P.accent))}
            scrimColour={P.pageBackground}
            scrim={veilAlpha(modeBg.imageTransparency, modeBg.img === BG_CUSTOM ? backgrounds.customLuma : bgPreset?.luma, actualMode)}
          />
        )}
        {children}
      </ThemeProvider>
    </ThemeContext.Provider>
  );
};

// ---- typography hook ---------------------------------------------------------------------------

/**
 * Read the active typography scale (TASK-100). `slot(role)` returns the role's Sx with the
 * current user size multiplier baked in, so a single helper covers every place a label can
 * live. Consumers should pass the result to `sx={{ ... }}`:
 *
 *     const t = useTypography();
 *     <Box sx={t.slot('pageTitle')}>Heading</Box>
 *     <Box sx={t.slotStyle('cardTitle')}>Title</Box>
 *
 *  - `size`: the user's choice ('sm' | 'md' | 'lg')
 *  - `multiplier`: 0.875 .. 1.125 — informational only: the html root already carries it
 *  - `setSize(s)`: the picker calls this; `null` clears the user choice (theme wins)
 */
export const useTypography = (): {
  size: SizeId;
  multiplier: number;
  setSize: (s: SizeId | null) => void;
  slot: (role: TypographyRole) => { fontSize: string; fontWeight: number; lineHeight: number };
  slotStyle: typeof slotStyle;
} => {
  const ctx = useTheme();
  return {
    size: ctx.size,
    multiplier: ctx.sizeMultiplier,
    setSize: ctx.setUserSize,
    slot: (role) => slotStyle(role),  // the multiplier lives on the html root, never bake it in again
    slotStyle,
  };
};
