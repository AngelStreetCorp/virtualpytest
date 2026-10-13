// System role ids, most privileged first. Fixed: what an installation calls them — the
// preferred name, also the name an external platform sends — comes from GET /server/roles.
export type Role = 'admin' | 'manager' | 'developer' | 'tester' | 'viewer';

// Fine-grained resource:action permissions
export type Permission =
  // Dashboard
  | 'dashboard:view'
  // Device control
  | 'device_control:view'
  | 'device_control:execute'
  | 'device_control:reboot'
  | 'device_control:restart_streams'
  | 'device_control:pair'
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
  | 'reports.tests:share'
  | 'reports.campaigns:view'
  | 'reports.models:view'
  | 'reports.dependency:view'
  // Run management (TASK-42): governance, defects, sharing and manual runs
  | 'reports.runs:edit'
  | 'reports.defects:edit'
  | 'reports.share:create'
  | 'reports.manual:execute'
  // Monitoring
  | 'monitoring.incidents:view'
  | 'monitoring.heatmap:view'
  | 'monitoring.ai_queue:view'
  | 'monitoring.public_ask:view'
  // Interface (navigation trees)
  | 'interface:view'
  | 'interface:create'
  | 'interface:edit'
  | 'interface:delete'
  // AI agent
  | 'ai_agent:view'
  | 'ai_agent:use'
  | 'ai.training:view'
  | 'ai.training:review'
  // Plugins
  | 'plugins.grafana:view'
  | 'plugins.langfuse:view'
  | 'plugins.postman:view'
  | 'plugins.jira:view'
  | 'plugins.jira:manage'
  | 'plugins.testrail:view'
  | 'plugins.testrail:manage'
  | 'plugins.slack:view'
  | 'plugins.gitlab:view'
  | 'plugins.gitlab:manage'
  // Settings
  | 'settings.general:view'
  | 'settings.general:edit'
  | 'settings.models:view'
  | 'settings.models:edit'
  | 'settings.code_deploy:view'
  | 'settings.code_deploy:use'
  | 'settings.cicd:view'
  | 'settings.cicd:edit'
  | 'settings.branding:view'
  | 'settings.branding:edit'
  | 'settings.status:view'
  | 'settings.logs:view'
  | 'system.services:restart'
  | 'system.hosts:run_command'
  | 'security:view'
  // Organisation
  | 'org.users:view'
  | 'org.users:create'
  | 'org.users:edit'
  | 'org.users:delete'
  | 'org.roles:view'
  | 'org.roles:edit'
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
  // TASK-31: the team permission ceiling from the `team_ceiling` claim. null/absent = no limit.
  team_ceiling?: Permission[] | null;
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

// All permissions in the system (for matrix/checkbox UI)
export const ALL_PERMISSIONS: Permission[] = [
  'dashboard:view',
  'device_control:view', 'device_control:execute', 'device_control:reboot', 'device_control:restart_streams',
  'device_control:pair',
  'testcases:view', 'testcases:create', 'testcases:edit', 'testcases:delete', 'testcases:hide',
  'campaigns:view', 'campaigns:create', 'campaigns:edit', 'campaigns:delete', 'campaigns:execute',
  'builder.test:view', 'builder.test:use',
  'builder.campaign:view', 'builder.campaign:use',
  'execution.run:view', 'execution.run:run_test', 'execution.run:run_campaign',
  'execution.monitor:view',
  'execution.build:view', 'execution.build:use',
  'reports.tests:view', 'reports.tests:share', 'reports.campaigns:view', 'reports.models:view', 'reports.dependency:view',
  'reports.runs:edit', 'reports.defects:edit', 'reports.share:create', 'reports.manual:execute',
  'monitoring.incidents:view', 'monitoring.heatmap:view', 'monitoring.ai_queue:view',
  'monitoring.public_ask:view',
  'interface:view', 'interface:create', 'interface:edit', 'interface:delete',
  'ai_agent:view', 'ai_agent:use',
  'ai.training:view', 'ai.training:review',
  'plugins.grafana:view', 'plugins.langfuse:view', 'plugins.postman:view',
  'plugins.jira:view', 'plugins.jira:manage', 'plugins.testrail:view', 'plugins.testrail:manage', 'plugins.slack:view',
  'plugins.gitlab:view', 'plugins.gitlab:manage',
  'settings.general:view', 'settings.general:edit',
  'settings.models:view', 'settings.models:edit',
  'settings.code_deploy:view', 'settings.code_deploy:use',
  'settings.cicd:view', 'settings.cicd:edit',
  'settings.branding:view', 'settings.branding:edit',
  'settings.status:view',
  'settings.logs:view',
  'system.services:restart', 'system.hosts:run_command',
  'security:view',
  'org.users:view', 'org.users:create', 'org.users:edit', 'org.users:delete',
  'org.roles:view', 'org.roles:edit',
  'org.teams:view', 'org.teams:create', 'org.teams:edit', 'org.teams:delete', 'org.teams:manage_members',
  'org.invite:send',
  'org.workspaces:view', 'org.workspaces:create', 'org.workspaces:edit',
  'org.workspaces:delete', 'org.workspaces:manage_members',
];

// All admin-expanded permissions (used when role === 'admin')
export const ADMIN_ALL_PERMISSIONS: Permission[] = ALL_PERMISSIONS;

// Default permissions of each role, as served by GET /server/roles (editable on the Roles page).
export type RoleDefaults = Record<Role, Permission[]>;

// One entry of the role catalog (GET /server/roles → catalog), sorted by rank (0 = admin).
// A non-admin may only edit users, and give roles, ranked strictly below their own.
export interface RoleInfo {
  role: Role;
  display_name: string;
  rank: number;
  editable: boolean; // false for admin: holds every permission
  allowed_devices: string[] | null; // device ceiling of the role, null = every device
}

// Where a permission stands for a user (TASK-31), the legend on the Users page:
//   role    held, from the role's defaults
//   grant   held, an individual grant beyond the role
//   denied  the role or a grant would give it, an explicit denial takes it away
//   capped  the role or a grant would give it, the team ceiling blocks it
//   none    not held
export type PermissionSource = 'role' | 'grant' | 'denied' | 'capped' | 'none';

export function permissionSource(
  perm: Permission,
  role: Role,
  roleDefaults: readonly string[] = [],
  teamCeiling: readonly string[] | null | undefined = null,
  grants: readonly string[] = [],
  denied: readonly string[] = [],
): PermissionSource {
  if (role === 'admin') return 'role';
  const fromRole = roleDefaults.includes(perm);
  if (!fromRole && !grants.includes(perm)) return 'none';
  if (denied.includes(perm)) return 'denied';
  if (teamCeiling && !teamCeiling.includes(perm)) return 'capped';
  return fromRole ? 'role' : 'grant';
}

// Effective permissions: (role defaults ∪ individual grants − denials) ∩ team ceiling.
// A team never grants; its ceiling (null = no limit) only caps. Admins always hold everything.
export function computeEffectivePermissions(
  role: Role,
  roleDefaults: readonly string[] = [],
  teamCeiling: readonly string[] | null | undefined = null,
  grants: readonly string[] = [],
  denied: readonly string[] = [],
): Permission[] {
  if (role === 'admin') return ADMIN_ALL_PERMISSIONS;
  return ALL_PERMISSIONS.filter((p) => {
    const src = permissionSource(p, role, roleDefaults, teamCeiling, grants, denied);
    return src === 'role' || src === 'grant';
  });
}

// Page → permission needed to see it (in the nav) and open it (route guard). The single
// table for page visibility: ProtectedRoute and WorkspaceContext.isPathHidden both read it via
// requiredPermissionForPath(). A key covers its sub-paths ('/test-plan/campaigns/42').
// Pages absent from the table (docs, analytics, ...) are open to every signed-in user.
export const PAGE_PERMISSIONS: Record<string, Permission> = {
  '/': 'dashboard:view',
  '/device-control': 'device_control:view',
  '/device-info': 'device_control:view',
  '/configuration/interface': 'interface:view',
  // Chatting is the page's only action, and a viewer cannot start a conversation (read-only floor).
  '/ai-agent': 'ai_agent:use',
  '/agent-dashboard': 'ai_agent:view',
  '/builder/test-builder': 'builder.test:view',
  '/builder/quick-test': 'builder.test:view',
  '/builder/virtual-scripts': 'builder.test:view',
  '/builder/campaign-builder': 'builder.campaign:view',
  '/test-plan/test-cases': 'testcases:view',
  '/test-plan/requirements': 'testcases:view',
  '/test-plan/coverage': 'testcases:view',
  '/test-plan/campaigns': 'campaigns:view',
  '/test-execution/run-tests': 'execution.run:view',
  '/test-execution/cicd': 'execution.run:view',
  '/test-execution/monitor-tests': 'execution.monitor:view',
  '/test-execution/build-campaign': 'execution.build:view',
  '/test-results/reports': 'reports.tests:view',
  '/test-results/cicd-reports': 'reports.tests:view',
  '/test-results/model-reports': 'reports.models:view',
  '/test-results/dependency-report': 'reports.dependency:view',
  '/test-results/runs': 'reports.tests:view',
  '/test-results/live': 'reports.tests:view',
  '/test-results/groups': 'reports.tests:view',
  '/test-results/milestones': 'reports.tests:view',
  '/test-results/labels': 'reports.tests:view',
  '/test-results/defects': 'reports.tests:view',
  '/test-results/quality': 'reports.tests:view',
  '/test-results/run-management': 'reports.tests:view',
  '/test-results/custom-reports': 'reports.tests:view',
  '/test-results/manual': 'reports.manual:execute',
  '/monitoring/incidents': 'monitoring.incidents:view',
  '/monitoring/heatmap': 'monitoring.heatmap:view',
  '/monitoring/ai-queue': 'monitoring.ai_queue:view',
  '/monitoring/ai-usage': 'monitoring.ai_queue:view',
  '/grafana-dashboard': 'plugins.grafana:view',
  '/langfuse-dashboard': 'plugins.langfuse:view',
  '/api/workspaces': 'plugins.postman:view',
  '/api/workspace': 'plugins.postman:view',
  '/integrations/jira': 'plugins.jira:view',
  '/integrations/testrail': 'plugins.testrail:view',
  '/integrations/slack': 'plugins.slack:view',
  '/monitoring/gitlab': 'plugins.gitlab:view',
  '/configuration/logs': 'settings.logs:view',
  '/configuration/models': 'settings.models:view',
  '/configuration/settings': 'settings.general:view',
  '/configuration/code-deployment': 'settings.code_deploy:view',
  '/configuration/run-command': 'system.hosts:run_command',
  '/training-review': 'ai.training:view',
  '/status': 'settings.status:view',
  '/users': 'org.users:view',
  '/roles': 'org.roles:view',
  '/teams': 'org.teams:view',
  '/workspaces': 'org.workspaces:view',
};

/** The permission a page needs, from the most specific PAGE_PERMISSIONS key covering `path`. */
export function requiredPermissionForPath(path: string): Permission | null {
  let best: string | null = null;
  for (const key of Object.keys(PAGE_PERMISSIONS)) {
    const covers = key === '/' ? path === '/' : path === key || path.startsWith(`${key}/`);
    if (covers && (best === null || key.length > best.length)) best = key;
  }
  return best ? PAGE_PERMISSIONS[best] : null;
}
