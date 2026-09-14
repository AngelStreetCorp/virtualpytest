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
  gold: '#FFD700',              // Bright gold - skills, badges, awards, highlights
  success: '#22c55e',           // Success/pass state
  error: '#ef4444',             // Error/fail state
  agentBubble: '#262626',
  agentBorder: '#333333',
  userBubble: '#3a3a3a',
  userBorder: '#4a4a4a',
  borderColor: '#383838',
  hoverBg: '#2a2a2a',
  cardShadow: '0 2px 8px rgba(0,0,0,0.3)',
};

export const AGENT_CHAT_LAYOUT = {
  sidebarWidth: 240,
  rightPanelWidth: 320,
  maxRecentBackgroundTasks: 10, // Max number of recent background tasks to keep per agent
  maxStoredConversations: 20, // Max total conversations to keep in localStorage (prevents unlimited growth)
};

/**
 * Agent color palette (used for UI display of agent badges/avatars)
 */
export const AGENT_COLORS: Record<string, string> = {
  'assistant': AGENT_CHAT_PALETTE.accent,
  'monitor': '#4fc3f7',
  'analyzer': '#81c784',
  // Skill colors (for skill badges)
  'exploration-mobile': '#81c784',
  'exploration-web': '#4fc3f7',
  'exploration-stb': '#ba68c8',
  'execution': '#e57373',
  'design': '#ffb74d',
  'monitoring-read': '#4fc3f7',
};

/**
 * Element highlight colors for overlays (used to distinguish multiple UI elements)
 * Centralized array to ensure consistency across all overlay components
 */
export const ELEMENT_HIGHLIGHT_COLORS = [
  '#FF0000',                    // Red
  '#0066FF',                    // Blue
  AGENT_CHAT_PALETTE.gold,     // Gold (uses theme color)
  '#00CC00',                    // Green
  '#9900FF',                    // Purple
];
