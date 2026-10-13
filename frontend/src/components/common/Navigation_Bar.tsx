import { Box, Button } from '@mui/material';
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
import { useWorkspaceContext } from '../../contexts/workspace/WorkspaceContext';
import { useI18n } from '../../i18n/useI18n';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { PreferencesRows } from './PreferencesRows';
import NavigationDropdown from './Navigation_Dropdown';
import { navItemSx } from './Navigation_ItemStyle';
import NavigationGroupedDropdown from './Navigation_GroupedDropdown';
import { getEnv } from '../../config/constants';

const NavigationBar: React.FC = () => {
  const location = useLocation();
  const { isPathHidden } = useWorkspaceContext();
  const { t } = useI18n();
  const [slackUrl, setSlackUrl] = useState<string>('https://slack.com');
  const [testrailInstanceUrl, setTestrailInstanceUrl] = useState<string>('https://virtualpytest.testrail.io');

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

  useEffect(() => {
    const fetchTestRailConfig = async () => {
      try {
        const response = await fetch(buildServerUrl('/server/integrations/testrail/config'));
        const data = await response.json();
        const config = data?.config;
        if (data?.success && config?.base_url) {
          setTestrailInstanceUrl(config.base_url);
        }
      } catch {
        // The TestRail link is optional; users without plugin access simply do not see it.
      }
    };
    fetchTestRailConfig();
  }, []);

  // Langfuse URL from env — if set, the dropdown item opens externally
  const langfuseUrl = getEnv('VITE_LANGFUSE_URL') as string | undefined;
  const grafanaUrl = getEnv('VITE_GRAFANA_URL') as string | undefined;
  const integrationsItems = buildIntegrationsItems({ slackUrl, langfuseUrl, testrailInstanceUrl, grafanaUrl });

  const isActive = (path: string, prefix = false) =>
    prefix ? location.pathname.startsWith(path) : location.pathname === path;

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'stretch', // items fill the bar's height so the active underline sits on its edge
        alignSelf: 'stretch',
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
          sx={navItemSx(isActive(DASHBOARD_ITEM.path))}
        >
          {t(DASHBOARD_ITEM.label)}
        </Button>
      )}

      {/* Device Control */}
      {!isPathHidden(DEVICE_ITEM.path) && (
        <Button
          component={Link}
          to={DEVICE_ITEM.path}
          sx={navItemSx(isActive(DEVICE_ITEM.path))}
        >
          {t(DEVICE_ITEM.label)}
        </Button>
      )}

      {/* AI Agent */}
      <NavigationDropdown label={t('AI')} items={AI_AGENT_ITEMS} />

      {/* Test (grouped) */}
      <NavigationGroupedDropdown label={t('Test')} groups={TEST_GROUPS} />

      {/* User Interface */}
      {!isPathHidden(INTERFACE_ITEM.path) && (
        <Button
          component={Link}
          to={INTERFACE_ITEM.path}
          sx={navItemSx(isActive(INTERFACE_ITEM.path, true))}
        >
          {t(INTERFACE_ITEM.label)}
        </Button>
      )}

      {/* Monitoring */}
      <NavigationDropdown label={t('Monitoring')} items={MONITORING_ITEMS} />

      {/* Docs */}
      <NavigationDropdown label={t('Docs')} items={DOCS_ITEMS} />

      {/* Plugins (third-party integrations) */}
      <NavigationDropdown label={t('Plugins')} items={integrationsItems} />

      {/* Settings (configuration) */}
      <NavigationDropdown
        label={t('Settings')}
        items={CONFIGURATION_ITEMS}
        footer={<PreferencesRows />}
      />
    </Box>
  );
};

export default NavigationBar;
