/**
 * UI Theme Constants for Agent Chat
 * 
 * Centralized color palette and layout dimensions for the AI Agent Chat page.
 * 
 * CONSISTENCY RULE: Use these colors across all pages for a unified look.
 * - Primary accent: #d4a574 (muted gold)
 * - Skill/badge/highlight: #FFD700 (bright gold)
 * - Success: #22c55e (green)
 * - Error: #ef4444 (red)
 */

import { useTheme } from '@mui/material';

export const AGENT_CHAT_PALETTE = {
  background: '#1a1a1a',
  surface: '#242424',
  inputBg: '#2a2a2a',
  sidebarBg: '#1e1e1e',
  textPrimary: '#f0f0f0',
  textSecondary: '#9a9a9a',
  textMuted: '#666666',
  accent: '#d4a574',           // Primary accent (muted gold) - buttons, switches, main UI
  accentHover: '#c49464',       // Hover state for accent
  accentText: '#d4a574',        // Accent used as text/icon colour (selected item, links)
  gold: '#FFD700',              // Bright gold - skills, badges, awards, highlights
  success: '#22c55e',           // Success/pass state
  error: '#ef4444',             // Error/fail state
  warning: '#f59e0b',           // Run error (infra), not a test failure
  agentBubble: '#262626',
  agentBorder: '#333333',
  userBubble: '#3a3a3a',
  userBorder: '#4a4a4a',
  borderColor: '#383838',
  hoverBg: '#2a2a2a',
  cardShadow: '0 2px 8px rgba(0,0,0,0.3)',
  // Categorical series (one per speaker / line), muted to sit with the gold accent; never status.
  series: ['#d4a574', '#7aa6c2', '#a98bc7', '#c98b8b', '#8fbf9f'],
};

/** Light counterpart of AGENT_CHAT_PALETTE — warm grey page (#f2f0ec) so white cards stand out,
 * hairlines and grey text dark enough to read; the top bar is white (ThemeContext). */
export const AGENT_CHAT_PALETTE_LIGHT: typeof AGENT_CHAT_PALETTE = {
  background: '#f2f0ec',
  surface: '#ffffff',
  inputBg: '#ffffff',
  sidebarBg: '#ffffff',          // rails = card level, like dark (#1e1e1e ≈ surface); hairline separates
  textPrimary: '#141414',
  textSecondary: '#4a4a4a',
  textMuted: '#6e6e6e',
  accent: '#d4a574',
  accentHover: '#c49464',
  accentText: '#8f5f2e',        // #d4a574 is ~2:1 on white — darker gold for text
  gold: '#b8860b',              // Darker gold — #FFD700 is unreadable on white
  success: '#16a34a',
  error: '#dc2626',
  warning: '#b45309',
  agentBubble: '#f7f5f1',
  agentBorder: '#d9d4cc',
  userBubble: '#ebe7e0',
  userBorder: '#cfc9bf',
  borderColor: '#d9d4cc',
  hoverBg: '#ebe7e0',
  cardShadow: '0 1px 3px rgba(60,50,30,0.08)',
  series: ['#8f5f2e', '#3f6f8f', '#6f5596', '#9a4f4f', '#4f7f5f'],
};

/** Agent-chat palette for the current MUI theme mode (light or dark). */
export const useAgentChatPalette = (): typeof AGENT_CHAT_PALETTE =>
  useTheme().palette.mode === 'dark' ? AGENT_CHAT_PALETTE : AGENT_CHAT_PALETTE_LIGHT;

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
  // Skill colors (for skill badges)
  'exploration-mobile': 4,
  'exploration-web': 1,
  'exploration-stb': 2,
  'execution': 3,
  'design': 0,
  'monitoring-read': 1,
};

/** Badge colour of an agent or skill in the current palette (gold for unknown ids). */
export const agentColor = (id: string, P: typeof AGENT_CHAT_PALETTE): string => P.series[AGENT_SERIES[id] ?? 0];

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
