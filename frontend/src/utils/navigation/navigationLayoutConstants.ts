/**
 * Layout and style constants for navigation editor.
 * Extracted from NavigationEditor page for reuse and consistency.
 */

/** ReactFlow translate extent bounds */
export const TRANSLATE_EXTENT: [[number, number], [number, number]] = [
  [-5000, -5000],
  [10000, 10000],
];

/** ReactFlow node extent bounds */
export const NODE_EXTENT: [[number, number], [number, number]] = [
  [-5000, -5000],
  [10000, 10000],
];

/** Snap grid for node positioning */
export const SNAP_GRID: [number, number] = [15, 15];

/** ReactFlow container style */
export const REACT_FLOW_STYLE = { width: '100%', height: '100%' };

/** Node origin for ReactFlow */
export const NODE_ORIGIN: [number, number] = [0, 0];

/** Default viewport */
export const DEFAULT_VIEWPORT = { x: 0, y: 0, zoom: 1 };

/** Auto layout button position (top, left in px) */
export const AUTO_LAYOUT_BUTTON_TOP = 124;
export const AUTO_LAYOUT_BUTTON_LEFT = 15;
