/**
 * TestCase Builder Types
 * 
 * Defines the structure for visual testcase building with React Flow
 */

export enum BlockType {
  START = 'start',
  SUCCESS = 'success',
  FAILURE = 'failure',
  // A loop-only terminal: reaching it stops the loop early with a PASS (the
  // QuickTest "break on success" disposition). Behaves like SUCCESS but signals
  // the loop to stop instead of continuing to the next iteration.
  BREAK_SUCCESS = 'break_success',
  ACTION = 'action',
  VERIFICATION = 'verification',
  NAVIGATION = 'navigation',
  LOOP = 'loop'
}

export enum ConnectionType {
  SUCCESS = 'success',
  FAILURE = 'failure'
}

// Block data interfaces for each type.
//
// CONTAINER MODEL: an Action block holds a SEQUENCE of actions (press OK → wait
// → volume up) and a Verification block holds a SET of verifications combined
// with a pass condition — exactly like an edge's action_set and a node's
// verifications. The legacy single-command fields (command/params) are retained
// only because the QuickTest linear builder still emits them; the visual
// TestCaseBuilder writes the list fields below.
export interface ActionBlockData {
  /** Ordered sequence of actions run one after another. */
  actions?: any[];
  retry_actions?: any[];
  failure_actions?: any[];
  iterator?: number;
  // Legacy single-action shape (QuickTest compiler) — not written by the
  // visual builder anymore.
  command?: string;
  action_type?: string;
  params?: Record<string, any>;
}

export interface VerificationBlockData {
  /** Set of verifications evaluated together with verification_pass_condition. */
  verifications?: any[];
  /** 'all' = every verification must pass; 'any' = at least one. Defaults 'all'. */
  verification_pass_condition?: 'all' | 'any';
  // Legacy single-verification shape (QuickTest compiler).
  command?: string;
  verification_type?: string;
  reference?: string;
  threshold?: number;
  params?: Record<string, any>;
}

export interface NavigationBlockData {
  target_node_label?: string;
  target_node_id?: string;
}

export interface LoopBlockData {
  /** Fixed iteration count, or a `{variable}` placeholder resolved at run time. */
  iterations: number | string;
  /** Self-contained sub-graph (own START / SUCCESS / FAILURE [/ break_success]
   *  terminals) run once per iteration. This is the key the executor reads. */
  nested_blocks?: TestCaseGraph;
  /** What to do when an iteration reaches its FAILURE terminal: 'break'
   *  (default — stop, loop fails) or 'continue' (retry next iteration). */
  on_failure?: 'break' | 'continue';
}

// Base block interface
export interface TestCaseBlock {
  id: string;
  type: BlockType;
  position: { x: number; y: number };
  data: ActionBlockData | VerificationBlockData | NavigationBlockData | LoopBlockData | {};
}

// Connection between blocks
export interface TestCaseConnection {
  id: string;
  source: string;
  target: string;
  sourceHandle: 'success' | 'failure';
  targetHandle?: string;
  type: ConnectionType;
  style?: {
    stroke?: string;
    strokeWidth?: number;
  };
}

// Script I/O Configuration (for campaign orchestration)
export interface ScriptInput {
  name: string;
  /** 'string' | 'number' | 'boolean' | 'node' — 'node' is a navigation-node
   *  label; the Run-with-inputs dialog renders a node dropdown for it. */
  type: string;
  required: boolean;
  default?: any;
  description?: string;
  protected?: boolean; // Protected inputs cannot be deleted (e.g., host_name, device_name)
}

export interface ScriptOutput {
  name: string;
  type: string;
  sourceBlockId?: string;
  sourceOutputName?: string;
  sourceOutputPath?: string;
  description?: string;
}

export interface MetadataField {
  name: string;
  value?: any; // Direct value (if not linked)
  sourceBlockId?: string; // OR linked to block output
  sourceOutputName?: string;
  sourceOutputType?: string;
  description?: string;
}

// ✅ NEW: Source link for multi-source variables
export interface SourceLink {
  sourceBlockId: string;
  sourceOutputName: string;
  sourceOutputType: string;
  blockLabel?: string;
}

// ✅ NEW: Variable interface (supports multiple source links)
export interface Variable {
  name: string;
  type: string;
  value?: any; // Direct static value (if not linked)
  
  // ❌ OLD: Single link (kept for backward compatibility)
  sourceBlockId?: string;
  sourceOutputName?: string;
  sourceOutputType?: string;
  
  // ✅ NEW: Multiple links
  sourceLinks?: SourceLink[];
}

export interface ScriptConfig {
  inputs: ScriptInput[];
  outputs: ScriptOutput[];
  variables?: Variable[]; // ✅ NEW: Added variables field with proper typing
  metadata: {
    mode: 'append' | 'replace';
    fields: MetadataField[];
  }; // Backend expects object with mode and fields
}

// Complete testcase graph
export interface TestCaseGraph {
  nodes: TestCaseBlock[];
  edges: TestCaseConnection[];
  scriptConfig?: ScriptConfig; // Optional for backward compatibility
}

// Saved testcase (with metadata)
export interface SavedTestCase {
  id: string;
  name: string;
  description?: string;
  userinterface_name: string;
  graph: TestCaseGraph;
  created_at: string;
  updated_at: string;
  team_id: string;
}

// Execution-related types
export type ExecutionResultType = 'success' | 'failure' | 'error';

export interface StepResult {
  step_number: number;
  block_id: string;
  block_type: BlockType;
  success: boolean;
  message?: string;
  error?: string;
  execution_time_ms: number;
  screenshot_path?: string;
  timestamp: number;
}

export interface ExecutionResult {
  success: boolean;
  result_type?: ExecutionResultType; // success = reached SUCCESS block, failure = reached FAILURE block, error = execution problems
  current_step: number;
  total_steps: number;
  step_results: StepResult[];
  execution_time_ms: number;
  report_url?: string;
  error?: string;
}

export interface ExecutionState {
  isExecuting: boolean;
  currentBlockId: string | null;
  result: ExecutionResult | null;
}

// Block-level execution state (for unified execution tracking)
export interface BlockExecutionState {
  status: 'idle' | 'pending' | 'executing' | 'success' | 'failure' | 'error';
  startTime?: number;
  endTime?: number;
  duration?: number;
  error?: string;
  result?: any;
}

// Execution mode
export type ExecutionMode = 'idle' | 'single_block' | 'test_case';

// Form data for block configuration
export interface ActionForm extends ActionBlockData {
  isValid: boolean;
}

export interface VerificationForm extends VerificationBlockData {
  isValid: boolean;
}

export interface NavigationForm extends NavigationBlockData {
  isValid: boolean;
}

export interface LoopForm extends LoopBlockData {
  isValid: boolean;
}

