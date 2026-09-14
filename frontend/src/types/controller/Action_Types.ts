/**
 * Unified Action Types
 *
 * Simple, standard action format used across the entire application.
 * An action is an action - same everywhere it's used.
 * Mirrors the verification system structure.
 */

// =====================================================
// ACTION PARAMETER TYPES
// =====================================================

// Remote action parameters (for android_mobile, android_tv, etc.)
export interface RemoteActionParams {
  key?: string; // For press_key commands (UP, DOWN, LEFT, RIGHT, etc.)
  text?: string; // For input_text commands
  package?: string; // For launch_app/close_app commands
  x?: number; // For coordinate tap commands
  y?: number; // For coordinate tap commands
  element_id?: string; // For element interaction commands
  coordinates?: string; // For tap_coordinates commands (format: "x,y")
  direction?: string; // For swipe/scroll commands (up, down, left, right)
  amount?: number; // For scroll amount
  duration?: number; // For wait commands
}

// Desktop action parameters (for PyAutoGUI, Bash, etc.)
export interface DesktopActionParams {
  x?: number; // Mouse coordinates
  y?: number; // Mouse coordinates
  key?: string; // Key to press
  keys?: string[]; // Key combinations
  text?: string; // Text to type
  command?: string; // Bash command
  bash_command?: string; // Alternative bash command parameter
  working_dir?: string; // Working directory for bash commands
  timeout?: number; // Command timeout
  image_path?: string; // Path to image for image-based actions
  confidence?: number; // Image matching confidence
  region?: number[]; // Screen region [left, top, width, height]
  app_name?: string; // Application name to launch
  clicks?: number; // Scroll clicks
  interval?: number; // Typing interval
  filename?: string; // Screenshot filename
}

// Web action parameters (for Playwright)
export interface WebActionParams {
  url?: string; // URL to navigate to
  selector?: string; // CSS selector
  text?: string; // Text to input
  x?: number; // Click coordinates
  y?: number; // Click coordinates
  timeout?: number; // Action timeout
  script?: string; // JavaScript code
  follow_redirects?: boolean; // Whether to follow redirects
  element_types?: string; // Types of elements to dump
  include_hidden?: boolean; // Include hidden elements
  task?: string; // AI browser task description
}

// AV action parameters (for screenshot, streaming, etc.)
export interface AVActionParams {
  resolution?: string; // For streaming commands
  quality?: string; // For screenshot/streaming quality
  format?: string; // For output format
  duration?: number; // For recording duration
}

// Power action parameters (for power control)
export interface PowerActionParams {
  state?: 'on' | 'off' | 'restart'; // For power state commands
  delay?: number; // For delayed power operations
}

// Network action parameters (for network operations)
export interface NetworkActionParams {
  interface?: string; // Network interface name
  ip?: string; // IP address for network commands
  port?: number; // Port for network commands
  protocol?: string; // Protocol (tcp, udp, etc.)
}

// Timer action parameters (for auto-return and timed actions)
export interface TimerActionParams {
  timer?: number; // Timer duration in milliseconds (0 = permanent, >0 = auto-return)
  target_node_id?: string; // Target node to return to
  action?: 'auto_return' | 'timeout' | 'delay'; // Type of timer action
}

// Union type for all action parameters
export type ActionParams =
  | RemoteActionParams
  | AVActionParams
  | PowerActionParams
  | NetworkActionParams
  | TimerActionParams;

// =====================================================
// ACTION INTERFACES
// =====================================================

// Base action interface
interface BaseAction {
  id: string; // Required: unique action identifier
  label: string; // Required: human-readable label
  command: string; // Required: command to execute
  description: string; // Required: action description
  action_type: 'remote' | 'av' | 'power' | 'network' | 'timer' | 'verification' | 'desktop' | 'web'; // Required: type of action
  requiresInput?: boolean; // Optional: whether action requires user input
  inputLabel?: string; // Optional: label for input field
  inputPlaceholder?: string; // Optional: placeholder for input field
  verification_type?: 'text' | 'image' | 'adb' | 'appium' | 'audio' | 'video'; // Optional: verification type for verification actions

  // Execution state (optional, populated during execution)
  waitTime?: number; // Optional: wait time after execution
  inputValue?: string; // Optional: user-provided input value

  // Result state (optional, populated after execution)
  success?: boolean;
  message?: string;
  error?: string;
  resultType?: 'SUCCESS' | 'FAILED' | 'ERROR';
  executionTime?: number;
  executedAt?: string;
}

// Specific action types with typed parameters
export interface RemoteAction extends BaseAction {
  action_type: 'remote';
  params: RemoteActionParams;
}

export interface AVAction extends BaseAction {
  action_type: 'av';
  params: AVActionParams;
}

export interface PowerAction extends BaseAction {
  action_type: 'power';
  params: PowerActionParams;
}

export interface DesktopAction extends BaseAction {
  action_type: 'desktop';
  params: DesktopActionParams;
}

export interface WebAction extends BaseAction {
  action_type: 'web';
  params: WebActionParams;
}

export interface NetworkAction extends BaseAction {
  action_type: 'network';
  params: NetworkActionParams;
}

export interface TimerAction extends BaseAction {
  action_type: 'timer';
  params: TimerActionParams;
}

export interface VerificationAction extends BaseAction {
  action_type: 'verification';
  verification_type: 'text' | 'image' | 'adb' | 'appium' | 'audio' | 'video';
  params: any; // Verification actions use various param structures
}

// Unified action type (discriminated union)
export type Action = RemoteAction | AVAction | PowerAction | DesktopAction | WebAction | NetworkAction | TimerAction | VerificationAction;

// Actions grouped by action type (mirrors Verifications structure)
export interface Actions {
  [actionType: string]: Action[]; // Action type as category (remote, av, power, network)
}

// =====================================================
// CONTROLLER ACTION MAPPING
// =====================================================

/**
 * Device Model to Action Controller Mapping
 * Maps device models to their supported action controllers
 */
export const DEVICE_MODEL_ACTION_MAPPING = {
  android_mobile: ['remote', 'av', 'power'],
  android_tv: ['remote', 'av', 'power'],
  fire_tv: ['remote', 'av', 'power'],
  ios_phone: ['remote', 'av'],
  ios_mobile: ['remote', 'av'],
  stb: ['remote', 'av', 'power', 'network'],
  host_vnc: ['desktop', 'web', 'av'],
  host_pyautogui: ['desktop', 'web', 'av'],
} as const;

export type DeviceModel = keyof typeof DEVICE_MODEL_ACTION_MAPPING;
export type ActionControllerType = 'remote' | 'av' | 'power' | 'desktop' | 'web' | 'network' | 'timer';

/**
 * Get action controller types for a device model
 */
export function getActionControllersForModel(model: string): ActionControllerType[] {
  return [...(DEVICE_MODEL_ACTION_MAPPING[model as DeviceModel] || [])];
}

/**
 * Check if a device model supports a specific action controller
 */
export function supportsActionController(
  model: string,
  controllerType: ActionControllerType,
): boolean {
  const supportedControllers = getActionControllersForModel(model);
  return supportedControllers.includes(controllerType);
}

// =====================================================
// EDGE ACTION TYPES (for navigation)
// =====================================================

// Edge action for navigation workflows (used in EdgeEditDialog)
export interface EdgeAction {
  command: string;
  name: string;
  params: ActionParams;
  action_type?: 'remote' | 'av' | 'power' | 'network'; // Action type
  requiresInput?: boolean; // Whether action requires user input
  inputValue?: string; // User-provided input value

  // Execution results (added by frontend during execution)
  success?: boolean;
  message?: string;
  error?: string;
  executedAt?: string;
  resultType?: 'SUCCESS' | 'FAIL' | 'ERROR';
  executionTime?: number; // Execution time in milliseconds
}

// Controller actions organized by category (what EdgeEditDialog expects)
export interface ControllerActions {
  [category: string]: Action[];
}
