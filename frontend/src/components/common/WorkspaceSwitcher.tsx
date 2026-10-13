import React from 'react';
import { FormControl, InputLabel, Select, MenuItem } from '@mui/material';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { useI18n } from '../../i18n/useI18n';

interface WorkspaceSwitcherProps {
  size?: 'small' | 'medium';
  minWidth?: number;
  variant?: 'outlined' | 'standard' | 'filled';
}

// "All" is no workspace at all: every device, script and page the user's role allows. It is not a
// stored row (an empty device_filter means NO devices, and a stored list would go stale as devices
// are added), so every server has it and nobody can edit or delete it.
const ALL_VALUE = '__all__';
export const ALL_WORKSPACE_LABEL = 'All';

const WorkspaceSwitcher: React.FC<WorkspaceSwitcherProps> = ({
  size = 'small',
  minWidth = 160,
  variant = 'outlined',
}) => {
  const { t } = useI18n();
  const { userWorkspaces, activeWorkspace, setActiveWorkspace } = useWorkspaceContext();

  const dedupedWorkspaces = React.useMemo(() => {
    const seen = new Set<string>();
    return userWorkspaces.filter((ws) => {
      if (seen.has(ws.id)) return false;
      seen.add(ws.id);
      return true;
    });
  }, [userWorkspaces]);

  const value = activeWorkspace?.id ?? ALL_VALUE;

  const renderSelectedValue = (v: unknown): string => {
    if (v === ALL_VALUE) return t('All');
    return dedupedWorkspaces.find((ws) => ws.id === v)?.name ?? '';
  };

  return (
    <FormControl size={size} sx={{ minWidth }} variant={variant}>
      <InputLabel>{t('Workspace')}</InputLabel>
      <Select
        value={value}
        label={t('Workspace')}
        onChange={(e) => {
          const v = e.target.value;
          setActiveWorkspace(v === ALL_VALUE ? null : v);
        }}
        // renderValue keeps the Select button on default MUI typography so it
        // matches ServerSelector — otherwise compact MenuItem styles leak in.
        renderValue={renderSelectedValue}
        MenuProps={{
          PaperProps: {
            sx: {
              '& .MuiList-root': { py: 0.25 },
              '& .MuiMenuItem-root': {
                minHeight: 28,
                py: 0.25,
                px: 1,
                fontSize: '0.8125rem',
                lineHeight: 1.2,
              },
            },
          },
        }}
        sx={{
          '& .MuiSelect-select': {
            display: 'flex',
            alignItems: 'center',
          },
        }}
      >
        <MenuItem value={ALL_VALUE}>{t('All')}</MenuItem>
        {dedupedWorkspaces.map((ws) => (
          <MenuItem key={ws.id} value={ws.id}>
            {ws.name}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
};

export default WorkspaceSwitcher;
