/**
 * AI Agent TypeScript Interfaces
 * Defines types for AI agent execution, steps, and task management
 */

export interface AIStep {
  step: number;
  type?: string;
  command: string;
  description: string;
  params?: Record<string, any>;
  estimatedDuration?: number;
}

export interface AIPlan {
  id: string;
  prompt: string;
  analysis: string;
  feasible: boolean;
  steps: AIStep[];
  
  // Legacy compatibility
  plan?: AIStep[];
  estimated_time?: string;
  risk_level?: 'low' | 'medium' | 'high';
}

export interface AIExecutionLogEntry {
  timestamp: number | string;
  log_type: string;
  action_type: 'plan_generated' | 'plan_ready' | 'step_start' | 'step_success' | 'step_failed' | 'task_completed' | 'task_failed';
  data: {
    step?: number;
    duration?: number;
    success?: boolean;
    command?: string;
    description?: string;
    plan_id?: string;
    feasible?: boolean;
    step_count?: number;
    analysis?: string;
    total_steps?: number;
    successful_steps?: number;
    failed_steps?: number;
  };
  value: any;
  description: string;
  
  // Legacy compatibility
  type?: string;
}

export interface AIStepResult {
  step: number;
  command: string;
  success: boolean;
  duration: number;
  error?: string;
}

export interface AITaskExecution {
  id: string;
  taskDescription: string;
  startTime: number;
  endTime?: number;
  totalDuration?: number;
  steps: AIStep[];
  executedSteps: AIStepResult[];
  success: boolean;
  summary: string;
}

export interface AIExecutionSummary {
  totalSteps: number;
  completedSteps: number;
  failedSteps: number;
  totalDuration: number;
  averageStepDuration: number;
  success: boolean;
  message: string;
}

export interface AITaskResult {
  success: boolean;
  message: string;
  executionDetails: {
    total_executed: number;
    total_planned: number;
    actions_executed: number;
    actions_planned: number;
    verifications_executed: number;
    verifications_planned: number;
  };
  summary: AIExecutionSummary;
}

// Enhanced execution status from backend
export interface AIExecutionStatus {
  success: boolean;
  is_executing: boolean;
  current_step: string;
  execution_log: AIExecutionLogEntry[];
  progress_percentage: number;
  plan?: AIPlan;
  step_results?: Array<{  // Execution results with transitions
    step_id: number;
    success: boolean;
    message?: string;
    execution_time_ms?: number;
    transitions?: any[];  // Navigation transitions from execution
  }>;
  execution_summary?: {
    total_steps: number;
    completed_steps: number;
    failed_steps: number;
    start_time: number;
    end_time?: number;
    total_duration: number;
  };
}

// Error categorization
export type AIErrorType = 
  | 'ai_timeout'
  | 'ai_connection_error' 
  | 'ai_auth_error'
  | 'ai_rate_limit'
  | 'ai_call_exception'
  | 'ai_call_failed'
  | 'navigation_error'
  | 'network_error'
  | 'unknown_error';

export interface AIError {
  message: string;
  type?: AIErrorType;
  context?: string;
}

export const AI_CONSTANTS = {
  POLL_INTERVAL: 2000,
  MAX_WAIT_TIME: 300000,
  TOAST_DURATION: {
    INFO: 2000,
    SUCCESS: 4000,
    ERROR: 5000,
  },
  PROGRESS_COLORS: {
    CURRENT: '#2196f3',
    SUCCESS: '#4caf50',
    FAILED: '#f44336',
    PENDING: '#666',
  }
} as const;
