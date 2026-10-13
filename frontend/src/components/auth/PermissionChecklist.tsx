import React from 'react';
import { Box, Checkbox, Divider, FormControlLabel, FormGroup, Typography } from '@mui/material';
import { ALL_PERMISSIONS, Permission } from '../../types/auth';

const PERMISSION_GROUPS: Record<string, string> = {
  dashboard: 'Dashboard',
  device_control: 'Device Control',
  testcases: 'Test Cases',
  campaigns: 'Campaigns',
  'builder.test': 'Builder - Test',
  'builder.campaign': 'Builder - Campaign',
  'execution.run': 'Execution - Run',
  'execution.monitor': 'Execution - Monitor',
  'execution.build': 'Execution - Build',
  'reports.tests': 'Reports - Tests',
  'reports.campaigns': 'Reports - Campaigns',
  'reports.models': 'Reports - Models',
  'reports.dependency': 'Reports - Dependency',
  'reports.runs': 'Reports - Runs',
  'reports.defects': 'Reports - Defects',
  'reports.share': 'Reports - Sharing',
  'reports.manual': 'Reports - Manual Runs',
  'monitoring.incidents': 'Monitoring - Incidents',
  'monitoring.heatmap': 'Monitoring - Heatmap',
  'monitoring.ai_queue': 'Monitoring - AI Queue',
  'monitoring.public_ask': 'Monitoring - Public Ask',
  interface: 'Interface',
  ai_agent: 'AI Agent',
  'ai.training': 'AI Dataset',
  'plugins.grafana': 'Plugins - Grafana',
  'plugins.langfuse': 'Plugins - Langfuse',
  'plugins.postman': 'Plugins - Postman',
  'plugins.jira': 'Plugins - Jira',
  'plugins.testrail': 'Plugins - TestRail',
  'plugins.slack': 'Plugins - Slack',
  'settings.general': 'Settings - General',
  'settings.models': 'Settings - Models',
  'settings.code_deploy': 'Settings - Code Deploy',
  'settings.cicd': 'Settings - CI/CD',
  'settings.branding': 'Settings - Branding',
  'settings.status': 'Settings - Status',
  'settings.logs': 'Settings - Logs',
  'system.services': 'System - Services',
  'system.hosts': 'System - Hosts',
  security: 'Security',
  'org.users': 'Org - Users',
  'org.roles': 'Org - Roles',
  'org.teams': 'Org - Teams',
  'org.invite': 'Org - Invite',
  'org.workspaces': 'Org - Workspaces',
};

function groupPermissions(perms: Permission[]): [string, Permission[]][] {
  const groups = new Map<string, Permission[]>();
  for (const perm of perms) {
    const prefix = perm.substring(0, perm.indexOf(':'));
    groups.set(prefix, [...(groups.get(prefix) ?? []), perm]);
  }
  return Array.from(groups.entries());
}

const GROUPED_PERMISSIONS = groupPermissions(ALL_PERMISSIONS);

interface PermissionChecklistProps {
  isChecked: (perm: Permission) => boolean;
  onToggle: (perm: Permission) => void;
  isDisabled?: (perm: Permission) => boolean;
  // Optional short tag after the action name, e.g. "granted" / "denied".
  renderTag?: (perm: Permission) => React.ReactNode;
  // Optional label colour per permission (a theme palette path, e.g. "success.main").
  labelColor?: (perm: Permission) => string | undefined;
}

export interface LegendItem {
  color: string;
  label: string;
}

/** A row of coloured swatches explaining what each label colour means. */
export const PermissionLegend: React.FC<{ items: LegendItem[] }> = ({ items }) => (
  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 2 }}>
    {items.map((item) => (
      <Box key={item.label} sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
        <Box sx={{ width: 12, height: 12, borderRadius: '2px', bgcolor: item.color }} />
        <Typography variant="caption">{item.label}</Typography>
      </Box>
    ))}
  </Box>
);

/** Every permission, grouped by resource, one checkbox each. */
export const PermissionChecklist: React.FC<PermissionChecklistProps> = ({
  isChecked,
  onToggle,
  isDisabled,
  renderTag,
  labelColor,
}) => (
  <>
    {GROUPED_PERMISSIONS.map(([prefix, perms]) => (
      <Box key={prefix} sx={{ mb: 2 }}>
        <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 0.5 }}>
          {PERMISSION_GROUPS[prefix] ?? prefix}
        </Typography>
        <Divider sx={{ mb: 1 }} />
        <FormGroup row>
          {perms.map((perm) => (
            <FormControlLabel
              key={perm}
              control={
                <Checkbox
                  size="small"
                  checked={isChecked(perm)}
                  onChange={() => onToggle(perm)}
                  disabled={isDisabled?.(perm)}
                />
              }
              label={
                <Typography variant="body2" color={labelColor?.(perm)}>
                  {perm.substring(perm.indexOf(':') + 1)}
                  {renderTag?.(perm)}
                </Typography>
              }
              sx={{ minWidth: 220 }}
            />
          ))}
        </FormGroup>
      </Box>
    ))}
  </>
);
