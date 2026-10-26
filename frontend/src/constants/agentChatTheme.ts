/**
 * UI Theme Constants for Agent Chat
 * 
 * Centralized color palette and layout dimensions for the AI Agent Chat page.
 * 
 * CONSISTENCY RULE: Use these colors across all pages for a unified look.
 * - Colours come from the active theme (themeEngine.ts); gold is the built-in default.
 * - Success / error / warning are fixed and never themed.
 */

import { useTheme } from '@mui/material';

import { DerivedPalettes, Palette, derivePalettes } from './themeEngine';
import { listThemes, loadCustom, loadProvided, loadSelected, resolveTheme } from './themeStore';

/**
 * The active palettes. `AGENT_CHAT_PALETTE` / `AGENT_CHAT_PALETTE_LIGHT` are live objects kept
 * for non-React code (module-level constants, canvas/SVG colours): `setActivePalettes` updates
 * them in place when the user switches theme. Components use `useAgentChatPalette()`, which
 * returns a fresh object per switch so memo dependencies notice.
 */
const initial = derivePalettes(
  resolveTheme(listThemes(loadProvided(), loadCustom()), loadSelected()),
);

export const AGENT_CHAT_PALETTE: Palette = { ...initial.dark };
export const AGENT_CHAT_PALETTE_LIGHT: Palette = { ...initial.light };

let activePalettes: DerivedPalettes = { dark: { ...initial.dark }, light: { ...initial.light } };

const paletteListeners: Array<() => void> = [];

/** Run `fn` after every palette switch (module-level colour constants rebuild themselves here). */
export const onPalettesChange = (fn: () => void): void => {
  paletteListeners.push(fn);
};

let lastApplied: DerivedPalettes | null = null;

export const setActivePalettes = (next: DerivedPalettes): void => {
  if (next === lastApplied) return;
  lastApplied = next;
  Object.assign(AGENT_CHAT_PALETTE, next.dark);
  Object.assign(AGENT_CHAT_PALETTE_LIGHT, next.light);
  activePalettes = { dark: { ...next.dark }, light: { ...next.light } };
  paletteListeners.forEach((fn) => fn());
};

/** Agent-chat palette for the current MUI theme mode (light or dark) and the active colour theme. */
export const useAgentChatPalette = (): Palette =>
  useTheme().palette.mode === 'dark' ? activePalettes.dark : activePalettes.light;

export const AGENT_CHAT_LAYOUT = {
  sidebarWidth: 240,
  rightPanelWidth: 320,
  maxRecentBackgroundTasks: 10, // Max number of recent background tasks to keep per agent
  maxStoredConversations: 20, // Max total conversations to keep in localStorage (prevents unlimited growth)
};

/**
 * Agent / skill badge colours: an index into the palette's categorical `series` (0 = gold accent),
 * resolved per theme by `agentColor(id, P)`.
 */
const AGENT_SERIES: Record<string, number> = {
  'assistant': 0,
  'monitor': 1,
  'analyzer': 4,
  'scripter': 2,
  'masterchief': 3,
  // Skill colors (for skill badges)
  'exploration-mobile': 4,
  'exploration-web': 1,
  'exploration-stb': 2,
  'execution': 3,
  'design': 0,
  'monitoring-read': 1,
};

/** Badge colour of an agent or skill in the current palette (gold for unknown ids). */
export const agentColor = (id: string, P: Palette): string => P.series[AGENT_SERIES[id] ?? 0];

/**
 * Element highlight colors for overlays (used to distinguish multiple UI elements)
 * Centralized array to ensure consistency across all overlay components.
 * palette: drawn ON screenshots / device screens — saturated on purpose so boxes read on any image.
 */
export const ELEMENT_HIGHLIGHT_COLORS = [
  '#FF0000',                    // Red
  '#0066FF',                    // Blue
  AGENT_CHAT_PALETTE.gold,     // Gold (uses theme color)
  '#00CC00',                    // Green
  '#9900FF',                    // Purple
];
