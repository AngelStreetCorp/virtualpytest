import React from 'react';
import { FormControl, InputLabel, Select, MenuItem } from '@mui/material';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';

interface WorkspaceSwitcherProps {
  size?: 'small' | 'medium';
  minWidth?: number;
  variant?: 'outlined' | 'standard' | 'filled';
}

const DEFAULT_VALUE = '__default__';

const WorkspaceSwitcher: React.FC<WorkspaceSwitcherProps> = ({
  size = 'small',
  minWidth = 160,
  variant = 'outlined',
}) => {
  const { userWorkspaces, activeWorkspace, setActiveWorkspace } = useWorkspaceContext();

  const dedupedWorkspaces = React.useMemo(() => {
    const seen = new Set<string>();
    return userWorkspaces.filter((ws) => {
      if (seen.has(ws.id)) return false;
      seen.add(ws.id);
      return true;
    });
  }, [userWorkspaces]);

  if (dedupedWorkspaces.length === 0) {
    return null;
  }

  const value = activeWorkspace?.id ?? DEFAULT_VALUE;

  const renderSelectedValue = (v: unknown): string => {
    if (v === DEFAULT_VALUE) return 'Default';
    return dedupedWorkspaces.find((ws) => ws.id === v)?.name ?? '';
  };

  return (
    <FormControl size={size} sx={{ minWidth }} variant={variant}>
      <InputLabel>Workspace</InputLabel>
      <Select
        value={value}
        label="Workspace"
        onChange={(e) => {
          const v = e.target.value;
          setActiveWorkspace(v === DEFAULT_VALUE ? null : v);
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
        <MenuItem value={DEFAULT_VALUE}>Default</MenuItem>
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
