/**
 * Campaign Execution Types
 * 
 * TypeScript interfaces for the campaign execution system.
 * These types define the structure for campaign configuration, execution tracking,
 * and script management within campaigns.
 */

// Campaign Configuration Types
export interface CampaignConfig {
  campaign_id: string;
  name: string;
  version_number?: number;
  description?: string;
  userinterface_name: string;
  host: string;
  device: string;
  callback_url?: string;
  callback_on_script_complete?: boolean;
  callback_on_campaign_complete?: boolean;
  execution_config: CampaignExecutionConfig;
  script_configurations: ScriptConfiguration[];
  force_unlock?: boolean;
}

export interface CampaignExecutionConfig {
  continue_on_failure: boolean;
  timeout_minutes: number;
  parallel: boolean;
}

export interface ScriptConfiguration {
  script_name: string;
  script_type: string;
  testcase_id?: string;  // NEW: For testcase execution
  description?: string;
  parameters: { [key: string]: any };
  order: number;
}

// Campaign Execution Tracking Types
export interface CampaignExecution {
  id: string;
  campaign_id: string;
  campaign_name: string;
  hostName: string;
  deviceId: string;
  deviceModel?: string;
  startTime: string;
  endTime?: string;
  status: CampaignStatus;
  overall_success?: boolean;
  current_script?: string;
  current_script_index?: number;
  total_scripts: number;
  completed_scripts: number;
  successful_scripts: number;
  failed_scripts: number;
  script_executions: ScriptExecutionStatus[];
  execution_config: CampaignExecutionConfig;
  reportUrl?: string;
  logsUrl?: string;
}

export type CampaignStatus = 'pending' | 'running' | 'completed' | 'failed' | 'aborted';

export interface ScriptExecutionStatus {
  script_name: string;
  script_type: string;
  description?: string;
  order: number;
  status: ScriptStatus;
  startTime?: string;
  endTime?: string;
  execution_time_ms?: number;
  success?: boolean;
  reportUrl?: string;
  logsUrl?: string;
  error_message?: string;
  parameters?: { [key: string]: any };
}

export type ScriptStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

// Campaign Builder Types
export interface CampaignBuilderState {
  config: Partial<CampaignConfig>;
  selectedHost: string;
  selectedDevice: string;
  availableScripts: string[];
  scriptAnalysisCache: { [scriptName: string]: ScriptAnalysis };
  isValid: boolean;
  validationErrors: string[];
}

export interface ScriptAnalysis {
  script_name: string;
  parameters: ScriptParameter[];
  description?: string;
  estimated_duration?: number;
}

export interface ScriptParameter {
  name: string;
  type: 'positional' | 'optional';
  required: boolean;
  help: string;
  default?: string;
  suggestions?: {
    suggested?: string;
    confidence?: string;
  };
}

// NEW: TestCase information for campaign builder
export interface TestCaseInfo {
  id: string;
  name: string;
  description?: string;
  scriptConfig?: {
    inputs?: Array<{ name: string; type?: string }>;
    outputs?: Array<{ name: string; type?: string }>;
    metadata?: {
      mode: 'set' | 'append';
      fields: Array<{ name: string }>;
    };
  };
}

// Campaign API Response Types
export interface CampaignExecutionResult {
  success: boolean;
  message: string;
  campaign_id: string;
  execution_id: string;
  campaign_result_id?: string;
  async: boolean;
  status: CampaignStatus;
  result?: {
    campaign_execution_id: string;
    overall_success: boolean;
    execution_time_ms: number;
    total_scripts: number;
    successful_scripts: number;
    failed_scripts: number;
    script_executions: ScriptExecutionResult[];
    error?: string;
    orchestrator_report_url?: string;
    orchestrator_logs_url?: string;
  };
}

export interface ScriptExecutionResult {
  script_name: string;
  success: boolean;
  execution_time_ms: number;
  script_result_id?: string;
  error?: string;
  report_url?: string;
  logs_url?: string;
}

// Campaign History & Results Types
export interface CampaignHistoryItem {
  id: string;
  campaign_name: string;
  campaign_id: string;
  execution_id: string;
  hostName: string;
  deviceId?: string;
  deviceModel?: string;
  startTime: string;
  endTime?: string;
  duration?: string;
  status: CampaignStatus;
  overall_success?: boolean;
  total_scripts: number;
  successful_scripts: number;
  failed_scripts: number;
  reportUrl?: string;
  logsUrl?: string;
}

// Validation Types
export interface CampaignValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface ScriptConfigurationValidation {
  script_name: string;
  valid: boolean;
  errors: string[];
  parameter_errors: { [paramName: string]: string };
}

// Campaign Templates (for future use)
export interface CampaignTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  config: Omit<CampaignConfig, 'campaign_id' | 'host' | 'device'>;
  tags: string[];
  created_at: string;
  usage_count: number;
}
