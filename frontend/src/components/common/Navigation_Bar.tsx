import { DarkMode, LightMode, SettingsBrightness } from '@mui/icons-material';
import { Box, Button, Divider, ListItemIcon, ListItemText, ListSubheader, MenuItem } from '@mui/material';
import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';

import {
  AI_AGENT_ITEMS,
  CONFIGURATION_ITEMS,
  DASHBOARD_ITEM,
  DEVICE_ITEM,
  DOCS_ITEMS,
  INTERFACE_ITEM,
  MONITORING_ITEMS,
  TEST_GROUPS,
  buildIntegrationsItems,
} from '../../config/navItems';
import { useTheme } from '../../contexts/ThemeContext';
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import NavigationDropdown from './Navigation_Dropdown';
import NavigationGroupedDropdown from './Navigation_GroupedDropdown';
import { getEnv } from '../../config/constants';

const NavigationBar: React.FC = () => {
  const location = useLocation();
  const { isPathHidden } = useWorkspaceContext();
  const { mode, setMode } = useTheme();
  const [slackUrl, setSlackUrl] = useState<string>('https://slack.com');
  const navItemSx = {
    justifyContent: 'center',
    textAlign: 'center',
    textTransform: 'none',
    px: 1,
    py: 0.875,
    whiteSpace: 'nowrap',
    minWidth: 108,
    flexShrink: 0,
    '&:hover': {
      backgroundColor: 'rgba(255, 255, 255, 0.1)',
    },
  } as const;

  // Fetch Slack configuration from backend
  useEffect(() => {
    const fetchSlackConfig = async () => {
      try {
        const response = await fetch(buildServerUrl('/server/integrations/slack/config'));
        const data = await response.json();
        if (data.success && data.config?.url) {
          setSlackUrl(data.config.url);
        }
      } catch (error) {
        console.error('Failed to fetch Slack config:', error);
      }
    };
    fetchSlackConfig();
  }, []);

  // Langfuse URL from env — if set, the dropdown item opens externally
  const langfuseUrl = getEnv('VITE_LANGFUSE_URL') as string | undefined;
  const integrationsItems = buildIntegrationsItems({ slackUrl, langfuseUrl });

  const isActive = (path: string, prefix = false) =>
    prefix ? location.pathname.startsWith(path) : location.pathname === path;

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 0,
        width: '100%',
        flexWrap: 'nowrap',
      }}
    >
      {/* Dashboard */}
      {!isPathHidden(DASHBOARD_ITEM.path) && (
        <Button
          component={Link}
          to={DASHBOARD_ITEM.path}
          sx={{
            color: isActive(DASHBOARD_ITEM.path) ? 'secondary.main' : 'inherit',
            fontWeight: isActive(DASHBOARD_ITEM.path) ? 600 : 400,
            ...navItemSx,
          }}
        >
          {DASHBOARD_ITEM.label}
        </Button>
      )}

      {/* Device Control */}
      {!isPathHidden(DEVICE_ITEM.path) && (
        <Button
          component={Link}
          to={DEVICE_ITEM.path}
          sx={{
            color: isActive(DEVICE_ITEM.path) ? 'secondary.main' : 'inherit',
            fontWeight: isActive(DEVICE_ITEM.path) ? 600 : 400,
            ...navItemSx,
          }}
        >
          {DEVICE_ITEM.label}
        </Button>
      )}

      {/* AI Agent */}
      <NavigationDropdown label="AI" items={AI_AGENT_ITEMS} />

      {/* Test (grouped) */}
      <NavigationGroupedDropdown label="Test" groups={TEST_GROUPS} />

      {/* User Interface */}
      {!isPathHidden(INTERFACE_ITEM.path) && (
        <Button
          component={Link}
          to={INTERFACE_ITEM.path}
          sx={{
            color: isActive(INTERFACE_ITEM.path, true) ? 'secondary.main' : 'inherit',
            fontWeight: isActive(INTERFACE_ITEM.path, true) ? 600 : 400,
            ...navItemSx,
          }}
        >
          {INTERFACE_ITEM.label}
        </Button>
      )}

      {/* Monitoring */}
      <NavigationDropdown label="Monitoring" items={MONITORING_ITEMS} />

      {/* Docs */}
      <NavigationDropdown label="Docs" items={DOCS_ITEMS} />

      {/* Plugins (third-party integrations) */}
      <NavigationDropdown label="Plugins" items={integrationsItems} />

      {/* Settings (configuration) */}
      <NavigationDropdown
        label="Settings"
        items={CONFIGURATION_ITEMS}
        footer={
          <Box>
            <Divider sx={{ my: 0.5 }} />
            <ListSubheader sx={{ lineHeight: '28px', bgcolor: 'transparent' }}>Theme</ListSubheader>
            <MenuItem onClick={() => setMode('light')} selected={mode === 'light'} sx={{ py: 1, px: 2 }}>
              <ListItemIcon>
                <LightMode fontSize="small" />
              </ListItemIcon>
              <ListItemText primaryTypographyProps={{ variant: 'body2' }}>Light</ListItemText>
            </MenuItem>
            <MenuItem onClick={() => setMode('dark')} selected={mode === 'dark'} sx={{ py: 1, px: 2 }}>
              <ListItemIcon>
                <DarkMode fontSize="small" />
              </ListItemIcon>
              <ListItemText primaryTypographyProps={{ variant: 'body2' }}>Dark</ListItemText>
            </MenuItem>
            <MenuItem onClick={() => setMode('system')} selected={mode === 'system'} sx={{ py: 1, px: 2 }}>
              <ListItemIcon>
                <SettingsBrightness fontSize="small" />
              </ListItemIcon>
              <ListItemText primaryTypographyProps={{ variant: 'body2' }}>System</ListItemText>
            </MenuItem>
          </Box>
        }
      />
    </Box>
  );
};

export default NavigationBar;
