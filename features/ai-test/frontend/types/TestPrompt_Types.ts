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

export interface TestPromptExecution {
  id: string;
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
}

export interface TestPromptStep {
  phase: 'go_home' | 'navigate' | 'action' | 'criteria_check';
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

export const DEFAULT_TEST_PROMPT_FORM: TestPromptFormState = {
  name: '',
  targetScreenNodeId: '',
  targetScreenLabel: '',
  prompt: '',
  acceptanceCriteria: '',
};
