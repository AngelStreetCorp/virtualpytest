export type Role = 'admin' | 'tester' | 'viewer';

// Fine-grained resource:action permissions
export type Permission =
  // Dashboard
  | 'dashboard:view'
  // Device control
  | 'device_control:view'
  | 'device_control:execute'
  | 'device_control:reboot'
  | 'device_control:restart_streams'
  // Test cases
  | 'testcases:view'
  | 'testcases:create'
  | 'testcases:edit'
  | 'testcases:delete'
  | 'testcases:hide'
  // Campaigns
  | 'campaigns:view'
  | 'campaigns:create'
  | 'campaigns:edit'
  | 'campaigns:delete'
  | 'campaigns:execute'
  // Test builder
  | 'builder.test:view'
  | 'builder.test:use'
  // Campaign builder
  | 'builder.campaign:view'
  | 'builder.campaign:use'
  // Execution
  | 'execution.run:view'
  | 'execution.run:run_test'
  | 'execution.run:run_campaign'
  | 'execution.monitor:view'
  | 'execution.build:view'
  | 'execution.build:use'
  // Reports
  | 'reports.tests:view'
  | 'reports.campaigns:view'
  | 'reports.models:view'
  | 'reports.dependency:view'
  // Monitoring
  | 'monitoring.incidents:view'
  | 'monitoring.heatmap:view'
  | 'monitoring.ai_queue:view'
  // Interface (navigation trees)
  | 'interface:view'
  | 'interface:create'
  | 'interface:edit'
  | 'interface:delete'
  // AI agent
  | 'ai_agent:view'
  | 'ai_agent:use'
  // Plugins
  | 'plugins.grafana:view'
  | 'plugins.langfuse:view'
  | 'plugins.postman:view'
  | 'plugins.jira:view'
  | 'plugins.jira:manage'
  | 'plugins.testrail:view'
  | 'plugins.testrail:manage'
  | 'plugins.slack:view'
  // Settings
  | 'settings.general:view'
  | 'settings.general:edit'
  | 'settings.models:view'
  | 'settings.models:edit'
  | 'settings.code_deploy:view'
  | 'settings.code_deploy:use'
  | 'settings.cicd:view'
  | 'settings.branding:view'
  | 'settings.branding:edit'
  | 'settings.status:view'
  // Organisation
  | 'org.users:view'
  | 'org.users:edit'
  | 'org.users:delete'
  | 'org.teams:view'
  | 'org.teams:create'
  | 'org.teams:edit'
  | 'org.teams:delete'
  | 'org.teams:manage_members'
  | 'org.invite:send'
  | 'org.workspaces:view'
  | 'org.workspaces:create'
  | 'org.workspaces:edit'
  | 'org.workspaces:delete'
  | 'org.workspaces:manage_members';

export interface UserProfile {
  id: string;
  email: string | null;
  full_name: string | null;
  avatar_url: string | null;
  role: Role;
  permissions: Permission[];
  denied_permissions: Permission[];
  team_permissions: Permission[];
  // TASK-23: super-admin flag. Only true for the platform owner; regular
  // admins stay false. Surfaced in the profile dropdown and used to gate the
  // Tenants UI.
  is_platform_admin?: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuthUser {
  id: string;
  email: string | null;
  user_metadata?: {
    full_name?: string;
    avatar_url?: string;
  };
}

// Role-based permission defaults (starting point — can be augmented/denied per user/team)
export const ROLE_PERMISSIONS: Record<Role, Permission[] | ['*']> = {
  admin: ['*'], // All permissions
  tester: [
    'dashboard:view',
    'device_control:view',
    'device_control:execute',
    'testcases:view',
    'testcases:create',
    'testcases:edit',
    'testcases:hide',
    'campaigns:view',
    'campaigns:create',
    'campaigns:edit',
    'campaigns:execute',
    'builder.test:view',
    'builder.test:use',
    'builder.campaign:view',
    'builder.campaign:use',
    'execution.run:view',
    'execution.run:run_test',
    'execution.run:run_campaign',
    'execution.monitor:view',
    'reports.tests:view',
    'reports.campaigns:view',
    'reports.models:view',
    'reports.dependency:view',
    'monitoring.incidents:view',
    'monitoring.heatmap:view',
    'monitoring.ai_queue:view',
    'interface:view',
    'ai_agent:view',
    'ai_agent:use',
    'plugins.postman:view',
    'plugins.jira:view',
    'plugins.jira:manage',
    'plugins.testrail:view',
    'settings.status:view',
  ],
  viewer: [
    'dashboard:view',
    'testcases:view',
    'campaigns:view',
    'reports.tests:view',
    'reports.campaigns:view',
    'reports.models:view',
    'reports.dependency:view',
    'monitoring.incidents:view',
    'monitoring.heatmap:view',
    'monitoring.ai_queue:view',
    'device_control:view', // see host cards / status; :execute/:reboot/:restart_streams stay tester+admin-only
    'plugins.postman:view',
    'plugins.jira:view',
    'plugins.testrail:view',
    'plugins.slack:view',
    'plugins.grafana:view',
    'plugins.langfuse:view',
    'settings.status:view',
  ],
};

// All permissions in the system (for matrix/checkbox UI)
export const ALL_PERMISSIONS: Permission[] = [
  'dashboard:view',
  'device_control:view', 'device_control:execute', 'device_control:reboot', 'device_control:restart_streams',
  'testcases:view', 'testcases:create', 'testcases:edit', 'testcases:delete', 'testcases:hide',
  'campaigns:view', 'campaigns:create', 'campaigns:edit', 'campaigns:delete', 'campaigns:execute',
  'builder.test:view', 'builder.test:use',
  'builder.campaign:view', 'builder.campaign:use',
  'execution.run:view', 'execution.run:run_test', 'execution.run:run_campaign',
  'execution.monitor:view',
  'execution.build:view', 'execution.build:use',
  'reports.tests:view', 'reports.campaigns:view', 'reports.models:view', 'reports.dependency:view',
  'monitoring.incidents:view', 'monitoring.heatmap:view', 'monitoring.ai_queue:view',
  'interface:view', 'interface:create', 'interface:edit', 'interface:delete',
  'ai_agent:view', 'ai_agent:use',
  'plugins.grafana:view', 'plugins.langfuse:view', 'plugins.postman:view',
  'plugins.jira:view', 'plugins.jira:manage', 'plugins.testrail:view', 'plugins.testrail:manage', 'plugins.slack:view',
  'settings.general:view', 'settings.general:edit',
  'settings.models:view', 'settings.models:edit',
  'settings.code_deploy:view', 'settings.code_deploy:use',
  'settings.cicd:view',
  'settings.branding:view', 'settings.branding:edit',
  'settings.status:view',
  'org.users:view', 'org.users:edit', 'org.users:delete',
  'org.teams:view', 'org.teams:create', 'org.teams:edit', 'org.teams:delete', 'org.teams:manage_members',
  'org.invite:send',
  'org.workspaces:view', 'org.workspaces:create', 'org.workspaces:edit',
  'org.workspaces:delete', 'org.workspaces:manage_members',
];

// All admin-expanded permissions (used when role === 'admin')
export const ADMIN_ALL_PERMISSIONS: Permission[] = ALL_PERMISSIONS;

// Page-level permission requirements (resource:action format)
export const PAGE_PERMISSIONS: Record<string, Permission | null> = {
  '/': null,
  '/login': null,
  '/configuration/settings': 'settings.general:view',
  '/configuration/models': 'settings.models:view',
  '/api/workspaces': 'plugins.postman:view',
  '/integrations/jira': 'plugins.jira:view',
  '/integrations/testrail': 'plugins.testrail:view',
  '/test-execution/run-tests': 'execution.run:view',
  '/test-plan/test-cases': 'testcases:view',
  '/test-plan/campaigns': 'campaigns:view',
  '/builder/test-builder': 'builder.test:view',
  '/builder/campaign-builder': 'builder.campaign:view',
  '/status': 'settings.status:view',
};
