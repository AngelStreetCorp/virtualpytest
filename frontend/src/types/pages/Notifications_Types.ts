/**
 * Notification System Types
 * 
 * Simple notification configuration and history types.
 * Designed to be easily extensible for future enhancements.
 */

// =====================================================
// INTEGRATION TYPES
// =====================================================

export interface NotificationIntegration {
  id: string;
  name: string;
  type: 'email' | 'slack' | 'teams' | 'jira';
  enabled: boolean;
  config: EmailConfig | SlackConfig | TeamsConfig | JiraConfig;
  created_at: string;
  updated_at: string;
}

export interface EmailConfig {
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string; // Will be securely stored in backend
  from_email: string;
  from_name?: string;
  use_tls: boolean;
}

export interface SlackConfig {
  webhook_url: string; // Will be securely stored in backend
  channel?: string;
  username?: string;
}

export interface TeamsConfig {
  webhook_url: string; // Will be securely stored in backend
}

export interface JiraConfig {
  server_url: string;
  username: string;
  api_token: string; // Will be securely stored in backend
  project_key: string;
  issue_type: string;
}

// =====================================================
// NOTIFICATION RULES TYPES
// =====================================================

export interface NotificationRule {
  id: string;
  name: string;
  enabled: boolean;
  event_type: NotificationEventType;
  integration_ids: string[]; // Which integrations to use
  created_at: string;
  updated_at: string;
}

export type NotificationEventType = 
  | 'script_execution_complete'
  | 'script_execution_failed'
  | 'campaign_execution_complete'
  | 'campaign_execution_failed'
  | 'system_alert'
  | 'monitoring_incident';

// =====================================================
// NOTIFICATION HISTORY TYPES
// =====================================================

export interface NotificationHistory {
  id: string;
  event_type: NotificationEventType;
  integration_type: 'email' | 'slack' | 'teams' | 'jira';
  integration_name: string;
  recipient: string; // email address, channel name, etc.
  status: 'sent' | 'failed' | 'pending';
  message_preview: string;
  error_message?: string;
  sent_at: string;
  // Event context data
  event_data?: {
    script_name?: string;
    campaign_name?: string;
    host_name?: string;
    device_name?: string;
    success?: boolean;
    duration?: number;
  };
}

// =====================================================
// API PAYLOAD TYPES
// =====================================================

export interface NotificationIntegrationCreatePayload {
  name: string;
  type: 'email' | 'slack' | 'teams' | 'jira';
  enabled: boolean;
  config: EmailConfig | SlackConfig | TeamsConfig | JiraConfig;
}

export interface NotificationRuleCreatePayload {
  name: string;
  enabled: boolean;
  event_type: NotificationEventType;
  integration_ids: string[];
}

// =====================================================
// UI STATE TYPES
// =====================================================

export interface NotificationPageState {
  activeTab: 'integrations' | 'rules' | 'history';
  selectedIntegration?: NotificationIntegration;
  selectedRule?: NotificationRule;
  isCreating: boolean;
  isEditing: boolean;
}
