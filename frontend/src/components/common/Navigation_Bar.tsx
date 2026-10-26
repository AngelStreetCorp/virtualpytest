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
import { toPublicGitLabUrl } from '../../utils/gitlabUrl';
import { PreferencesRows } from './PreferencesRows';
import NavigationDropdown from './Navigation_Dropdown';
import { navItemSx, NavLabel } from './Navigation_ItemStyle';
import NavigationGroupedDropdown from './Navigation_GroupedDropdown';
import NavigationPagesDropdown from './Navigation_PagesDropdown';
import { getEnv } from '../../config/constants';
import { featureNavItems } from '../../config/features';
import { useAgentChatPalette } from '../../constants/agentChatTheme';

const NavigationBar: React.FC = () => {
  const location = useLocation();
  const { isPathHidden } = useWorkspaceContext();
  const { t } = useI18n();
  // Subscribe to palette changes so `navItemSx` re-reads `P.navHover` when the theme switches.
  useAgentChatPalette();
  const [slackUrl, setSlackUrl] = useState<string>('https://slack.com');
  const [testrailInstanceUrl, setTestrailInstanceUrl] = useState<string>('https://virtualpytest.testrail.io');
  const [gitlabUrl, setGitlabUrl] = useState<string>('');
  const [zammadUrl, setZammadUrl] = useState<string>('');

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

  // GitLab is configured per server, so the shortcut has to be re-read whenever the picker
  // moves to another server — a URL fetched once at mount would keep pointing at the previous
  // server's instance. `/server/gitlab/instances` reads the local store only (no probe of the
  // instance, and never returns the token), which is what makes it cheap enough for every page
  // load. Only fetched when the feature actually contributes a nav item, so a build with
  // DISABLED_FEATURES=gitlab never issues the request.
  useEffect(() => {
    if (!featureNavItems('plugins').some((i) => i.label === 'GitLab')) return;
    let cancelled = false;
    const fetchGitlabUrl = async () => {
      try {
        const response = await fetch(buildServerUrl('/server/gitlab/instances'));
        const data = await response.json();
        if (cancelled) return;
        const first = data?.instances?.[0];
        // Same-origin `/gitlab`, not the instance's own address: that address is internal to the
        // VPT server's network and a browser handed it gets a link that times out off-LAN.
        setGitlabUrl(
          data?.success && first?.base_url ? toPublicGitLabUrl(first.base_url) : '',
        );
      } catch {
        // No GitLab reachable on this server: the item simply shows no shortcut button.
        if (!cancelled) setGitlabUrl('');
      }
    };
    fetchGitlabUrl();
    const onServerChanged = () => { fetchGitlabUrl(); };
    window.addEventListener('vpt:server-changed', onServerChanged);
    return () => {
      cancelled = true;
      window.removeEventListener('vpt:server-changed', onServerChanged);
    };
  }, []);

  // Zammad's web UI is per server too (the feature's stored public_url). `/server/zammad/status`
  // is the cheap no-outbound status call the feature already uses for its navbar gate.
  useEffect(() => {
    if (!featureNavItems('plugins').some((i) => i.label === 'Zammad')) return;
    let cancelled = false;
    const fetchZammadUrl = async () => {
      try {
        const response = await fetch(buildServerUrl('/server/zammad/status'));
        const data = await response.json();
        if (cancelled) return;
        setZammadUrl(data?.success && data?.enabled && data?.public_url ? data.public_url : '');
      } catch {
        if (!cancelled) setZammadUrl('');
      }
    };
    fetchZammadUrl();
    const onServerChanged = () => { fetchZammadUrl(); };
    window.addEventListener('vpt:server-changed', onServerChanged);
    return () => {
      cancelled = true;
      window.removeEventListener('vpt:server-changed', onServerChanged);
    };
  }, []);

  // Langfuse URL from env — if set, the dropdown item opens externally
  const langfuseUrl = getEnv('VITE_LANGFUSE_URL') as string | undefined;
  const grafanaUrl = getEnv('VITE_GRAFANA_URL') as string | undefined;
  const integrationsItems = buildIntegrationsItems({ slackUrl, langfuseUrl, testrailInstanceUrl, grafanaUrl, gitlabUrl, zammadUrl });

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
        // BUG-0773: the row may never paint over the slot on its right (the "N online"
        // chip, the bell). The items shrink and their label ellipsizes instead.
        minWidth: 0,
        overflow: 'hidden',
      }}
    >
      {/* Dashboard */}
      {!isPathHidden(DASHBOARD_ITEM.path) && (
        <Button
          component={Link}
          to={DASHBOARD_ITEM.path}
          sx={navItemSx(isActive(DASHBOARD_ITEM.path))}
        >
          <NavLabel text={t(DASHBOARD_ITEM.label)} />
        </Button>
      )}

      {/* Device Control */}
      {!isPathHidden(DEVICE_ITEM.path) && (
        <Button
          component={Link}
          to={DEVICE_ITEM.path}
          sx={navItemSx(isActive(DEVICE_ITEM.path))}
        >
          <NavLabel text={t(DEVICE_ITEM.label)} />
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
          <NavLabel text={t(INTERFACE_ITEM.label)} />
        </Button>
      )}

      {/* Monitoring */}
      <NavigationDropdown label={t('Monitoring')} items={MONITORING_ITEMS} />

      {/* Custom pages (TASK-139) */}
      <NavigationPagesDropdown />

      {/* Docs */}
      <NavigationDropdown label={t('Docs')} items={DOCS_ITEMS} />

      {/* Plugins (third-party integrations) */}
      <NavigationDropdown label={t('Plugins')} items={integrationsItems} />

      {/* Settings (configuration) */}
      <NavigationDropdown
        label={t('Settings')}
        items={CONFIGURATION_ITEMS}
        footer={<PreferencesRows />}
        // BUG-0572: PreferencesRows fits inside the 240 px widest-locale
        // baseline (minWidth: 216 px, 20 px tall segments, microMeta icons), so
        // no override is strictly needed. The operator asked for ~10 px more
        // headroom around the Language row (EN / FR / DE buttons were brushing
        // the menu's right edge in a way that felt cramped on the longer DE
        // label), so we floor at 250 px. The other five dropdowns keep the 240
        // baseline (so language switching still does not resize them).
        minWidth={250}
      />
    </Box>
  );
};

export default NavigationBar;
