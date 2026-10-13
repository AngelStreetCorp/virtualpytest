/**
 * Validation Color Configuration
 * Centralized color management for React Flow nodes and edges based on validation status
 */

// Static palette import — these colours are baked into SVGs/CSS for React Flow nodes
// and must read on both themes, so we use the dark palette's categorical series.
// (No hooks possible in this .ts module.)
import { AGENT_CHAT_PALETTE } from '../constants/agentChatTheme';

const STEEL = AGENT_CHAT_PALETTE.series[1];
const GOLD = AGENT_CHAT_PALETTE.accent;
const GOLD_HOVER = AGENT_CHAT_PALETTE.accentHover;

// Node type base colors - these define the visual identity of different node types
export const NODE_TYPE_COLORS = {
  entry: {
    background: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}cc, ${AGENT_CHAT_PALETTE.error})`,
    border: AGENT_CHAT_PALETTE.accent,
    textColor: '#ffffff',
    badgeColor: AGENT_CHAT_PALETTE.accent,
  },
  menu: {
    background: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}1a, ${AGENT_CHAT_PALETTE.warning}33)`,
    border: AGENT_CHAT_PALETTE.accent,
    textColor: AGENT_CHAT_PALETTE.warning,
    badgeColor: AGENT_CHAT_PALETTE.warning,
  },
  screen: {
    background: `linear-gradient(135deg, ${STEEL}1a, ${STEEL}33)`,
    border: STEEL,
    textColor: STEEL,
    badgeColor: STEEL,
  },
  dialog: {
    background: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.series[2]}1a, ${AGENT_CHAT_PALETTE.series[2]}33)`,
    border: AGENT_CHAT_PALETTE.series[2],
    textColor: AGENT_CHAT_PALETTE.series[2],
    badgeColor: AGENT_CHAT_PALETTE.series[2],
  },
  popup: {
    background: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}1a, ${AGENT_CHAT_PALETTE.warning}33)`,
    border: AGENT_CHAT_PALETTE.warning,
    textColor: AGENT_CHAT_PALETTE.warning,
    badgeColor: AGENT_CHAT_PALETTE.warning,
  },
  overlay: {
    background: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}1a, ${AGENT_CHAT_PALETTE.success}33)`,
    border: AGENT_CHAT_PALETTE.success,
    textColor: AGENT_CHAT_PALETTE.success,
    badgeColor: AGENT_CHAT_PALETTE.success,
  },
  action: {
    background: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}1a, ${AGENT_CHAT_PALETTE.warning}33)`,
    border: AGENT_CHAT_PALETTE.warning,
    textColor: AGENT_CHAT_PALETTE.warning,
    badgeColor: AGENT_CHAT_PALETTE.warning,
  },
} as const;

// UI Badge colors for different badge types
export const UI_BADGE_COLORS = {
  root: {
    background: AGENT_CHAT_PALETTE.error,
    textColor: '#ffffff',
  },
  menu: {
    background: AGENT_CHAT_PALETTE.warning,
    textColor: '#ffffff',
  },
  entry: {
    background: AGENT_CHAT_PALETTE.accent,
    textColor: '#ffffff',
  },
  verification: AGENT_CHAT_PALETTE.series[2],
  subtree: STEEL,
} as const;

// Status colors based on validation confidence levels
export const VALIDATION_STATUS_COLORS = {
  untested: {
    border: AGENT_CHAT_PALETTE.textMuted,
    background: `${AGENT_CHAT_PALETTE.textMuted}1a`,
    handle: AGENT_CHAT_PALETTE.textMuted,
    glow: `${AGENT_CHAT_PALETTE.textMuted}4d`,
    textColor: AGENT_CHAT_PALETTE.textMuted,
  },
  testing: {
    border: GOLD,
    background: `${GOLD}26`,
    handle: GOLD,
    glow: `${GOLD}99`,
    textColor: GOLD_HOVER,
    animation: 'testing-pulse 2s ease-in-out infinite',
  },
  high: {
    // >70% confidence
    border: AGENT_CHAT_PALETTE.success,
    background: `${AGENT_CHAT_PALETTE.success}1a`,
    handle: AGENT_CHAT_PALETTE.success,
    glow: `${AGENT_CHAT_PALETTE.success}66`,
    textColor: AGENT_CHAT_PALETTE.success,
  },
  medium: {
    // 50-70% confidence
    border: AGENT_CHAT_PALETTE.warning,
    background: `${AGENT_CHAT_PALETTE.warning}1a`,
    handle: AGENT_CHAT_PALETTE.warning,
    glow: `${AGENT_CHAT_PALETTE.warning}66`,
    textColor: AGENT_CHAT_PALETTE.warning,
  },
  low: {
    // <50% confidence
    border: AGENT_CHAT_PALETTE.error,
    background: `${AGENT_CHAT_PALETTE.error}1a`,
    handle: AGENT_CHAT_PALETTE.error,
    glow: `${AGENT_CHAT_PALETTE.error}66`,
    textColor: AGENT_CHAT_PALETTE.error,
  },
} as const;

// Edge colors for different validation states
export const EDGE_COLORS = {
  untested: {
    stroke: AGENT_CHAT_PALETTE.textMuted,
    strokeWidth: 3,
    strokeDasharray: '',
    opacity: 0.6,
  },
  testing: {
    stroke: GOLD,
    strokeWidth: 3,
    strokeDasharray: '',
    opacity: 1,
    animation: 'edge-pulse 1.5s ease-in-out infinite',
  },
  high: {
    stroke: AGENT_CHAT_PALETTE.success,
    strokeWidth: 3,
    strokeDasharray: '',
    opacity: 1,
  },
  medium: {
    stroke: AGENT_CHAT_PALETTE.warning,
    strokeWidth: 3,
    strokeDasharray: '',
    opacity: 1,
  },
  low: {
    stroke: AGENT_CHAT_PALETTE.error,
    strokeWidth: 3,
    strokeDasharray: '5,5',
    opacity: 1,
  },
  entry: {
    stroke: GOLD,
    strokeWidth: 3,
    strokeDasharray: '',
    opacity: 1,
  },
} as const;

// Handle colors for different positions and states
export const HANDLE_COLORS = {
  // Left handles (horizontal navigation)
  leftTop: {
    untested: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.textMuted}, ${AGENT_CHAT_PALETTE.borderColor})`,
    testing: `linear-gradient(135deg, ${GOLD}, ${AGENT_CHAT_PALETTE.accentHover})`,
    high: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}cc, ${AGENT_CHAT_PALETTE.success})`,
    medium: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}cc, ${AGENT_CHAT_PALETTE.warning})`,
    low: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}cc, ${AGENT_CHAT_PALETTE.error}b3)`,
  },
  leftBottom: {
    untested: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}cc, ${AGENT_CHAT_PALETTE.warning}b3)`,
    testing: `linear-gradient(135deg, ${GOLD}, ${AGENT_CHAT_PALETTE.accentHover})`,
    high: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}, ${AGENT_CHAT_PALETTE.success}b3)`,
    medium: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}, ${AGENT_CHAT_PALETTE.warning}b3)`,
    low: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}b3, ${AGENT_CHAT_PALETTE.error})`,
  },
  // Right handles (horizontal navigation)
  rightTop: {
    untested: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.textMuted}, ${AGENT_CHAT_PALETTE.borderColor})`,
    testing: `linear-gradient(135deg, ${GOLD}, ${AGENT_CHAT_PALETTE.accentHover})`,
    high: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}, ${AGENT_CHAT_PALETTE.success}b3)`,
    medium: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}, ${AGENT_CHAT_PALETTE.warning}b3)`,
    low: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}, ${AGENT_CHAT_PALETTE.error}b3)`,
  },
  rightBottom: {
    untested: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}cc, ${AGENT_CHAT_PALETTE.error}b3)`,
    testing: `linear-gradient(135deg, ${GOLD}, ${AGENT_CHAT_PALETTE.accentHover})`,
    high: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}cc, ${AGENT_CHAT_PALETTE.success})`,
    medium: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}cc, ${AGENT_CHAT_PALETTE.warning})`,
    low: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}b3, ${AGENT_CHAT_PALETTE.error}cc)`,
  },
  // Top handles (menu navigation)
  topLeft: {
    untested: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.series[2]}cc, ${AGENT_CHAT_PALETTE.series[2]})`,
    testing: `linear-gradient(135deg, ${GOLD}, ${AGENT_CHAT_PALETTE.accentHover})`,
    high: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}, ${AGENT_CHAT_PALETTE.success}b3)`,
    medium: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}, ${AGENT_CHAT_PALETTE.warning}b3)`,
    low: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}cc, ${AGENT_CHAT_PALETTE.error})`,
  },
  topRight: {
    untested: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}cc, ${AGENT_CHAT_PALETTE.success}b3)`,
    testing: `linear-gradient(135deg, ${GOLD}, ${AGENT_CHAT_PALETTE.accentHover})`,
    high: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}, ${AGENT_CHAT_PALETTE.success}b3)`,
    medium: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}, ${AGENT_CHAT_PALETTE.warning}b3)`,
    low: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}, ${AGENT_CHAT_PALETTE.error}b3)`,
  },
  // Bottom handles (menu navigation)
  bottomLeft: {
    untested: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.series[2]}cc, ${AGENT_CHAT_PALETTE.series[2]}b3)`,
    testing: `linear-gradient(135deg, ${GOLD}, ${AGENT_CHAT_PALETTE.accentHover})`,
    high: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}cc, ${AGENT_CHAT_PALETTE.success})`,
    medium: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}cc, ${AGENT_CHAT_PALETTE.warning})`,
    low: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}cc, ${AGENT_CHAT_PALETTE.error}b3)`,
  },
  bottomRight: {
    untested: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}, ${AGENT_CHAT_PALETTE.success}cc)`,
    testing: `linear-gradient(135deg, ${GOLD}, ${AGENT_CHAT_PALETTE.accentHover})`,
    high: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.success}b3, ${AGENT_CHAT_PALETTE.success}e6)`,
    medium: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.warning}b3, ${AGENT_CHAT_PALETTE.warning}e6)`,
    low: `linear-gradient(135deg, ${AGENT_CHAT_PALETTE.error}b3, ${AGENT_CHAT_PALETTE.error}cc)`,
  },
} as const;

// Animation configurations
export const VALIDATION_ANIMATIONS = {
  testingPulse: {
    name: 'testing-pulse',
    duration: '2s',
    timing: 'ease-in-out',
    iteration: 'infinite',
    keyframes: `
      0% {
        transform: scale(1);
      }
      50% {
        transform: scale(1.02);
      }
      100% {
        transform: scale(1);
      }
    `,
  },
  edgePulse: {
    name: 'edge-pulse',
    duration: '1.5s',
    timing: 'ease-in-out',
    iteration: 'infinite',
    keyframes: `
      0% {
        opacity: 0.8;
        stroke-width: var(--base-width);
      }
      50% {
        opacity: 1;
        stroke-width: calc(var(--base-width) + 1);
      }
      100% {
        opacity: 0.8;
        stroke-width: var(--base-width);
      }
    `,
  },
  handleGlow: {
    name: 'handle-glow',
    duration: '2s',
    timing: 'ease-in-out',
    iteration: 'infinite',
    keyframes: `
      0% {
        opacity: 0.8;
      }
      50% {
        opacity: 1;
      }
      100% {
        opacity: 0.8;
      }
    `,
  },
} as const;

// Confidence level thresholds
export const CONFIDENCE_THRESHOLDS = {
  HIGH: 0.7,
  MEDIUM: 0.49,
} as const;

// Type definitions for validation status
export type ValidationStatus = 'untested' | 'testing' | 'high' | 'medium' | 'low';
export type NodeType = keyof typeof NODE_TYPE_COLORS;
export type HandlePosition = keyof typeof HANDLE_COLORS;

// Utility function to determine validation status from confidence and volume
export function getValidationStatusFromConfidence(confidence: number, volume?: number): ValidationStatus {
  // If volume is 0, it's untested (grey), not low confidence (red)
  if (volume !== undefined && volume === 0) return 'untested';

  if (confidence >= CONFIDENCE_THRESHOLDS.HIGH) return 'high';
  if (confidence >= CONFIDENCE_THRESHOLDS.MEDIUM) return 'medium';
  return 'low';
}

// Utility function to get CSS custom properties for animations
export function getAnimationCSS(): string {
  return `
    @keyframes ${VALIDATION_ANIMATIONS.testingPulse.name} {
      ${VALIDATION_ANIMATIONS.testingPulse.keyframes}
    }

    @keyframes ${VALIDATION_ANIMATIONS.edgePulse.name} {
      ${VALIDATION_ANIMATIONS.edgePulse.keyframes}
    }

    @keyframes ${VALIDATION_ANIMATIONS.handleGlow.name} {
      ${VALIDATION_ANIMATIONS.handleGlow.keyframes}
    }

    .node-testing {
      animation: ${VALIDATION_ANIMATIONS.testingPulse.name} ${VALIDATION_ANIMATIONS.testingPulse.duration} ${VALIDATION_ANIMATIONS.testingPulse.timing} ${VALIDATION_ANIMATIONS.testingPulse.iteration};
    }

    .edge-testing {
      animation: ${VALIDATION_ANIMATIONS.edgePulse.name} ${VALIDATION_ANIMATIONS.edgePulse.duration} ${VALIDATION_ANIMATIONS.edgePulse.timing} ${VALIDATION_ANIMATIONS.edgePulse.iteration};
    }

    .handle-testing {
      animation: ${VALIDATION_ANIMATIONS.handleGlow.name} ${VALIDATION_ANIMATIONS.handleGlow.duration} ${VALIDATION_ANIMATIONS.handleGlow.timing} ${VALIDATION_ANIMATIONS.handleGlow.iteration};
    }
  `;
}