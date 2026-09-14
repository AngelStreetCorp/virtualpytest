/**
 * Exploration Types - v2.0 (MCP-First Incremental)
 * 
 * Type definitions for the 4-phase AI exploration workflow
 */

export type ExplorationPhase = 'phase0' | 'phase1' | 'phase2' | 'phase3';

export type ExplorationStrategy = 
  | 'click_with_selectors'  // Mobile/Web with dump_ui_elements
  | 'click_with_text'       // Mobile/Web fallback
  | 'dpad_with_screenshot'; // TV/STB

export type PhaseStatus = 'pending' | 'running' | 'completed' | 'failed';

/**
 * Exploration Context - flows through all phases
 */
export interface ExplorationContext {
  // Original request
  original_prompt: string;
  tree_id: string;
  userinterface_name: string;
  device_model: string;
  device_id: string;
  host_name: string;
  team_id: string;
  
  // Phase 0 results
  strategy: ExplorationStrategy | null;
  has_dump_ui: boolean;
  available_elements: UIElement[];
  
  // Phase 1 results
  predicted_items: string[];
  item_selectors: Record<string, SelectorInfo>;
  screenshot_url: string | null;
  menu_type: string | null;
  
  // Phase 2 progress
  current_step: number;
  total_steps: number;
  completed_items: string[];
  failed_items: FailedItem[];
  
  // Metadata
  created_at: string;
  updated_at: string;
}

/**
 * Phase progress tracking
 */
export interface PhaseProgress {
  phase0: PhaseStatus;
  phase1: PhaseStatus;
  phase2: PhaseStatus;
  phase3: PhaseStatus;
}

/**
 * UI Element (from dump_ui_elements)
 */
export interface UIElement {
  text: string;
  resource_id?: string;
  class?: string;
  xpath?: string;
  bounds?: {x: number; y: number; width: number; height: number};
  clickable: boolean;
  focused: boolean;
  content_desc?: string;
}

/**
 * Selector information
 */
export interface SelectorInfo {
  type: 'css' | 'xpath' | 'resource_id' | 'text';
  value: string;
  bounds?: {x: number; y: number; width: number; height: number};
}

/**
 * Failed item information
 */
export interface FailedItem {
  item: string;
  error: string;
  step?: 'create_node' | 'create_edge' | 'execute_edge' | 'save_screenshot';
  edge_id?: string;
}

/**
 * Item creation result (Phase 2)
 */
export interface ItemCreationResult {
  success: boolean;
  item: string;
  node_created: boolean;
  edge_created: boolean;
  edge_tested: boolean;
  test_result?: 'success' | 'failed';
  error?: string;
  screenshot_url?: string;
  has_more_items: boolean;
  progress: {
    current_item: number;
    total_items: number;
  };
}

/**
 * Exploration plan (Phase 1 result)
 */
export interface ExplorationPlan {
  menu_type: string;
  items: string[];
  lines?: string[][];  // 2D array of items by row
  duplicate_positions?: string[];  // Position identifiers like "1_5" (row 1, index 5)
  strategy: ExplorationStrategy;
  has_exact_selectors: boolean;
  selectors: Record<string, SelectorInfo>;
  screenshot: string;
  reasoning?: string;
  edges_preview?: Array<{
    item: string;
    horizontal?: {
      source: string;
      target: string;
      forward_action: string;
      reverse_action: string;
    };
    vertical?: {
      source: string;
      target: string;
      forward_action: string;
      reverse_action: string;
    };
    click?: {
      source: string;
      target: string;
      forward_action: string;
      reverse_action: string;
    };
  }>;
}

/**
 * API Response types
 */

export interface StartExplorationResponse {
  success: boolean;
  exploration_id: string;
  host_name: string;
  message: string;
  context?: ExplorationContext;
}

export interface Phase0Response {
  success: boolean;
  strategy: ExplorationStrategy;
  has_dump_ui: boolean;
  available_elements?: UIElement[];
  context: ExplorationContext;
}

export interface ExplorationStatusResponse {
  success: boolean;
  exploration_id: string;
  status: string;
  phase: ExplorationPhase | null;
  current_step: string;
  progress: {
    total_screens_found: number;
    screens_analyzed: number;
    nodes_proposed: number;
    edges_proposed: number;
  };
  exploration_plan?: ExplorationPlan;
  error?: string;
}

export interface ContinueExplorationResponse {
  success: boolean;
  nodes_created: number;
  edges_created: number;
  message: string;
  items_to_process: string[];
  context: ExplorationContext;
}

export interface NextItemResponse {
  success: boolean;
  item: string;
  node_created: boolean;
  edge_created: boolean;
  edge_tested: boolean;
  has_more_items: boolean;
  error?: string;
  progress: {
    current_item: number;
    total_items: number;
  };
  context: ExplorationContext;
}

export interface FinalizeResponse {
  success: boolean;
  nodes_renamed: number;
  edges_renamed: number;
  message: string;
}

