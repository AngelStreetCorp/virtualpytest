export interface TestPromptFormState {
  name: string;
  targetScreenNodeId: string;
  targetScreenLabel: string;
  prompt: string;
  acceptanceCriteria: string;
}

export interface TestPrompt {
  id: string;
  name: string;
  prompt: string;
  acceptance_criteria: string;
  target_screen_node_id?: string;
  target_screen_label?: string;
  userinterface_name: string;
  version: number;
  parent_id?: string;
  mode: 'dev' | 'prod';
  testcase_id?: string;
  created_by?: string;
  created_at: string;
  updated_at: string;
}

/** explore = the Atlas agent drives the device; graph = the prompt's testcase graph runs on the testcase executor. */
export type TestPromptRunMode = 'explore' | 'graph' | 'auto';

export interface TestPromptExecution {
  id: string;
  mode?: TestPromptRunMode;
  /** Graph a graph run generated (none when it replayed the linked testcase) — what Save as testcase saves. */
  generatedGraph?: any;
  analysis?: string;
  savedTestcaseId?: string;
  executionId: string;
  testPromptId: string;
  status: 'queued' | 'running' | 'passed' | 'failed' | 'error';
  steps: TestPromptStep[];
  reportUrl?: string;
  logsUrl?: string;
  humanFeedback?: string;
  scriptResultId?: string;
  executionTimeMs?: number;
  version?: number;
  error?: string;
  startedAt?: number;
  completedAt?: number;
  /** What actually ran (the form's values, saved or not) and where. */
  ranPrompt?: string;
  ranCriteria?: string;
  ranTarget?: string;
  /** User interface the run targeted — same value shown in the form's Interface selector. */
  ranUserinterface?: string;
  /** The form differed from the saved version when the run started. */
  edited?: boolean;
  hostName?: string;
  deviceId?: string;
  /** Graph run: the linked testcase it replayed, or a graph generated for this run. */
  replayedTestcase?: { id: string; name?: string };
  generated?: boolean;
  /** Exploration: the agent's final report (criteria verdicts with evidence). */
  verdict?: string;
  /** Exploration: its device steps were recorded, so it can be saved as a testcase. */
  hasTrace?: boolean;
  /** Auto mode: this run was started by Auto; autoFrom / retryOf = the failed run it follows up. */
  auto?: boolean;
  autoFrom?: string;
  retryOf?: string;
  /** Auto mode, on a failed graph run: the decision model's pick (shadow until gated) and what followed. */
  decision?: { choice?: string; confidence?: number; probabilities?: Record<string, number>; action?: string; gated?: boolean; success?: boolean; error?: string };
  outcome?: { follow_up_execution_id?: string; follow_up_mode?: string; follow_up_status?: string };
}

export interface TestPromptStep {
  phase: 'go_home' | 'navigate' | 'action' | 'criteria_check' | 'graph';
  label: string;
  status: 'pending' | 'running' | 'passed' | 'failed';
  duration?: number;
  screenshotUrl?: string;
}

export interface TestPromptLiveEvent {
  // Stable unique id assigned client-side so React can use it as a key and
  // avoid re-rendering every visible row when the array shifts.
  id: string;
  type: string;
  content: string;
  toolName?: string;
  toolParams?: Record<string, unknown>;
  stepNumber?: number;
  timestamp: string;
}

export interface LinkedTestcase {
  id: string;
  name: string;
}

export const DEFAULT_TEST_PROMPT_FORM: TestPromptFormState = {
  name: '',
  targetScreenNodeId: '',
  targetScreenLabel: '',
  prompt: '',
  acceptanceCriteria: '',
};
