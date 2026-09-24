import { OpenInNew as ExternalIcon, Refresh as RefreshIcon } from '@mui/icons-material';
import { Box, IconButton, Link, Tab, Tabs, Tooltip, Typography } from '@mui/material';
import React, { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import {
  AlertsPanel,
  DevicesPanel,
  IncidentsPanel,
  KpiPanel,
  OverviewPanel,
  ProjectPanel,
  SystemPanel,
} from '../components/analytics/panels';
import { getEnv } from '../config/constants';
import DesktopOnlyPlaceholder from '../components/mobile/DesktopOnlyPlaceholder';
import { invalidateAnalytics, prefetchSection } from '../hooks/pages/useAnalytics';
import { useResponsiveMode } from '../hooks/useResponsiveMode';
import {
  ANALYTICS_SECTIONS,
  AnalyticsSection,
  ApiSection,
} from '../types/pages/Analytics_Types';

/**
 * Monitoring > Analytics — the basics without opening Grafana.
 *
 * TABS, NOT ONE SCROLL, and that is a performance decision rather than a styling one.
 * Seven sections is ~22 charts; mounting them all means that many recharts
 * ResponsiveContainers with their own ResizeObservers. More importantly the Devices
 * tab reads an aggregate that costs 1382 ms uncached, and a single-page layout would
 * make every visit pay for it. Only the active panel is mounted — do NOT add
 * `keepMounted` to the Tabs, or both savings evaporate.
 */

const TAB_LABELS: Record<AnalyticsSection, string> = {
  overview: 'Overview',
  system: 'System',
  devices: 'Devices',
  kpi: 'KPI',
  incidents: 'Incidents',
  alerts: 'Alerts',
  project: 'Project',
};

/**
 * The Grafana dashboard that goes deeper than each tab.
 *
 * One link per TAB, in the page header — not one per card. Per-card links repeated the
 * same destination up to four times on a tab and crowded the header badly enough that
 * "Disk usage" wrapped onto three lines and stopped lining up with its neighbours.
 * Tabs with no deeper equivalent (Project reads no database) simply have no link.
 */
const GRAFANA_UID: Partial<Record<AnalyticsSection, string>> = {
  overview: 'fe85e054-7760-4133-8118-3dfe663dee66',
  system: 'fe85e054-7760-4133-8118-3dfe663dee66',
  devices: 'vpt-fleet-health',
  kpi: 'script-results',
  incidents: 'device-alerts-dashboard',
  alerts: 'device-alerts-dashboard',
};

const grafanaLink = (section: AnalyticsSection): string | undefined => {
  const uid = GRAFANA_UID[section];
  const base = getEnv('VITE_GRAFANA_URL') || '';
  return uid && base ? `${base}/d/${uid}?orgId=1` : undefined;
};

const isSection = (value: string | null): value is AnalyticsSection =>
  !!value && (ANALYTICS_SECTIONS as readonly string[]).includes(value);

const MonitoringAnalytics: React.FC = () => {
  const { isMobile } = useResponsiveMode();
  const [searchParams, setSearchParams] = useSearchParams();

  // The tab lives in the URL so a section is linkable and survives a reload.
  const requested = searchParams.get('section');
  const active: AnalyticsSection = isSection(requested) ? requested : 'overview';

  const handleChange = useCallback(
    (_event: React.SyntheticEvent, value: AnalyticsSection) => {
      const next = new URLSearchParams(searchParams);
      if (value === 'overview') next.delete('section');
      else next.set('section', value);
      setSearchParams(next, { replace: true });
      console.log(`[@component:MonitoringAnalytics] section -> ${value}`);
    },
    [searchParams, setSearchParams],
  );

  // Hover is the cheapest possible signal of intent: by the time the click lands the
  // round trip has usually finished. 'project' is a static file, not a section.
  const handleHover = useCallback((section: AnalyticsSection) => {
    if (section !== 'project') prefetchSection(section as ApiSection);
  }, []);

  const handleRefresh = useCallback(() => {
    invalidateAnalytics();
    // Remount the active panel so its hook refetches.
    const next = new URLSearchParams(searchParams);
    next.set('_r', String(Date.now()));
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const panel = useMemo(() => {
    switch (active) {
      case 'system':
        return <SystemPanel />;
      case 'devices':
        return <DevicesPanel />;
      case 'kpi':
        return <KpiPanel />;
      case 'incidents':
        return <IncidentsPanel />;
      case 'alerts':
        return <AlertsPanel />;
      case 'project':
        return <ProjectPanel />;
      case 'overview':
      default:
        return <OverviewPanel />;
    }
  }, [active]);

  if (isMobile) {
    return <DesktopOnlyPlaceholder title="Analytics" />;
  }

  return (
    <Box sx={{ p: 3, pt: 2, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1.5, mb: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 600 }}>
          Analytics
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        {grafanaLink(active) && (
          <Link
            href={grafanaLink(active)}
            target="_blank"
            rel="noopener"
            underline="none"
            sx={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 0.5,
              fontSize: '0.75rem',
              color: 'text.secondary',
              '&:hover': { color: 'text.primary' },
            }}
          >
            Open in Grafana
            <ExternalIcon sx={{ fontSize: 13 }} />
          </Link>
        )}
        <Tooltip title="Refresh this tab">
          <IconButton size="small" onClick={handleRefresh}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      <Tabs
        value={active}
        onChange={handleChange}
        variant="scrollable"
        scrollButtons="auto"
        sx={{ borderBottom: 1, borderColor: 'divider', minHeight: 40, mb: 2 }}
      >
        {ANALYTICS_SECTIONS.map((section) => (
          <Tab
            key={section}
            value={section}
            label={TAB_LABELS[section]}
            onMouseEnter={() => handleHover(section)}
            onFocus={() => handleHover(section)}
            sx={{ minHeight: 40, textTransform: 'none', fontSize: '0.8125rem' }}
          />
        ))}
      </Tabs>

      {panel}
    </Box>
  );
};

export default MonitoringAnalytics;
