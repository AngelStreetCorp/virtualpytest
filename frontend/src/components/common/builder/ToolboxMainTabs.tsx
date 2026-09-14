/**
 * Toolbox Main Tabs Component
 * 
 * Shared tab selector for builder toolboxes (TestCase, Campaign).
 * Provides consistent Blocks / Config tab navigation.
 */

import React from 'react';
import { Box, Tabs, Tab } from '@mui/material';
import ViewModuleIcon from '@mui/icons-material/ViewModule';
import SettingsIcon from '@mui/icons-material/Settings';

export type ToolboxMainTabValue = 'blocks' | 'config';

interface ToolboxMainTabsProps {
  activeTab: ToolboxMainTabValue;
  onTabChange: (tab: ToolboxMainTabValue) => void;
  blocksCount: number;
  configCount: number;
}

export const ToolboxMainTabs: React.FC<ToolboxMainTabsProps> = ({
  activeTab,
  onTabChange,
  blocksCount,
  configCount,
}) => {
  return (
    <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
      <Tabs
        value={activeTab}
        onChange={(_, newValue) => onTabChange(newValue)}
        variant="fullWidth"
        sx={{
          minHeight: 36,
          '& .MuiTab-root': {
            minHeight: 36,
            py: 0.5,
            fontSize: 12,
            fontWeight: 500,
            textTransform: 'none',
          },
          '& .MuiTabs-indicator': {
            height: 2,
          },
        }}
      >
        <Tab 
          value="blocks" 
          icon={<ViewModuleIcon sx={{ fontSize: 16 }} />}
          iconPosition="start"
          label={`Functions (${blocksCount})`}
        />
        <Tab 
          value="config" 
          icon={<SettingsIcon sx={{ fontSize: 16 }} />}
          iconPosition="start"
          label={`Config (${configCount})`}
        />
      </Tabs>
    </Box>
  );
};

