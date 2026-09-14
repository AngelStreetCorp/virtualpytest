/**
 * Default positions for terminal nodes in both TestCase and Campaign builders
 * 
 * This ensures consistent layout across all builders.
 * Layout: START at top center, SUCCESS and FAILURE at bottom (left and right)
 */

export const DEFAULT_TERMINAL_POSITIONS = {
  start: { x: 400, y: 50 },      // Top center
  success: { x: 250, y: 550 },   // Bottom left
  failure: { x: 550, y: 550 },   // Bottom right
} as const;

/**
 * Default viewport settings for ReactFlow canvas
 * Ensures consistent zoom and position across all builders
 */
export const DEFAULT_VIEWPORT = {
  x: 0,
  y: 0,
  zoom: 0.8,  // Default zoom level
} as const;

/**
 * Zoom constraints for ReactFlow canvas
 */
export const ZOOM_CONSTRAINTS = {
  minZoom: 0.2,
  maxZoom: 2,
} as const;

/**
 * FitView options for consistent view fitting across builders
 */
export const FIT_VIEW_OPTIONS = {
  padding: 0.2,
  duration: 200,
} as const;

/**
 * Creates default terminal nodes for builders (START, SUCCESS, FAILURE)
 * Used by both TestCaseBuilder and CampaignBuilder
 */
export const createDefaultTerminalNodes = () => [
  {
    id: 'start',
    type: 'start',
    position: { ...DEFAULT_TERMINAL_POSITIONS.start },
    data: {},
    deletable: false,
  },
  {
    id: 'success',
    type: 'success',
    position: { ...DEFAULT_TERMINAL_POSITIONS.success },
    data: {},
    deletable: false,
  },
  {
    id: 'failure',
    type: 'failure',
    position: { ...DEFAULT_TERMINAL_POSITIONS.failure },
    data: {},
    deletable: false,
  },
];

