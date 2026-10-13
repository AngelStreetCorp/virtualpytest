export type RunOutcome = 'running' | 'passed' | 'failed';

export interface RunRow {
  id: string;
  kind: string;
  status: string;
  outcome: RunOutcome;
  progress?: number;
  step?: string;
  stepNumber?: number;
  totalSteps?: number;
  message?: string;
  hostName?: string;
  deviceId?: string;
  error?: string;
  startedAt: number;
  updatedAt: number;
}

export interface RunProgressState {
  rows: Record<string, RunRow>;
  /** Band hidden by the user until the next new run. */
  hidden: boolean;
}

export interface RunSummary {
  running: number;
  passed: number;
  failed: number;
  total: number;
  /** Overall 0–100, finished runs counted as 100. */
  percent: number;
}
