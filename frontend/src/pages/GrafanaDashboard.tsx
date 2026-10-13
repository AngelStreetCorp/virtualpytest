import { Box, FormControl, InputLabel, MenuItem, Select, SelectChangeEvent, Tooltip, Typography } from '@mui/material';
import { OpenInNew } from '@mui/icons-material';
import React, { useEffect, useState } from 'react';
import { getEnv } from '../config/constants';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';
import { withGrafanaWorkspace } from '../utils/grafanaUrl';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { useTheme } from '../contexts/ThemeContext';

interface Dashboard {
  title: string;
  uid: string;
  slug: string;
}

const GrafanaDashboard: React.FC = () => {
  const P = useAgentChatPalette();
  // Grafana follows the app theme (it was always light, a white block in dark mode).
  const { actualMode } = useTheme();
  const { activeWorkspace } = useWorkspaceContext();
  // Get Grafana URL from environment variable
  const grafanaUrl = getEnv('VITE_GRAFANA_URL') || 'http://localhost/grafana';

  // Only dashboards every deployment has. Customer- or project-specific ones (FullZap, per-project
  // quality) are provisioned by that deployment's own Grafana and must not be listed here.
  const allDashboards: Dashboard[] = [
    {
      title: 'Server Monitoring',
      uid: 'system-monitoring',
      slug: 'system-monitoring'
    },
    {
      title: 'Service Status',
      uid: 'system-service-status',
      slug: 'system-service-status'
    },
    {
      title: 'Host Monitoring',
      uid: 'fe85e054-7760-4133-8118-3dfe663dee66',
      slug: 'system-host-monitoring'
    },
    {
      title: 'Device Alerts',
      uid: 'device-alerts-dashboard',
      slug: 'device-alerts-dashboard'
    },
    {
      title: 'Script Results',
      uid: '2a3b060a-7820-4a6e-aa2a-adcbf5408bd3',
      slug: 'script-results'
    },
    {
      title: 'Navigation Metrics',
      uid: '9369e579-7f7a-47ec-ae06-f3a49e530b4f',
      slug: 'navigation-metrics'
    }
  ];

  // Open on Script Results: Server Monitoring is about the platform's own server, and a viewer
  // without access to it landed on a 403 "Failed to load dashboard" on first open.
  const [selectedDashboard, setSelectedDashboard] = useState<string>('2a3b060a-7820-4a6e-aa2a-adcbf5408bd3');

  // Grafana's search returns only the dashboards this viewer may open; list just those so nobody
  // picks one that ends in a 403. If the search cannot be reached (other host, no session), keep
  // the full list.
  const [visibleUids, setVisibleUids] = useState<Set<string> | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetch(`${grafanaUrl}/api/search?type=dash-db&limit=5000`, { credentials: 'include' })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((rows: Array<{ uid: string }>) => {
        if (!cancelled && Array.isArray(rows)) setVisibleUids(new Set(rows.map(r => r.uid)));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [grafanaUrl]);

  const dashboards = visibleUids ? allDashboards.filter(d => visibleUids.has(d.uid)) : allDashboards;

  useEffect(() => {
    if (dashboards.length > 0 && !dashboards.some(d => d.uid === selectedDashboard)) {
      setSelectedDashboard(dashboards[0].uid);
    }
  }, [dashboards, selectedDashboard]);

  const handleDashboardChange = (event: SelectChangeEvent<string>) => {
    setSelectedDashboard(event.target.value);
  };

  const selectedDashboardData = dashboards.find(d => d.uid === selectedDashboard);

  return (
    // Fill the app's content area, not the viewport: this page already sits below the
    // AppHeader inside the app scroll container, so 100vh overflowed it and added a
    // second scrollbar next to the one Grafana draws inside the iframe.
    <Box sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {/* Dashboard Selector */}
      <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: P.borderColor, display: 'flex', alignItems: 'center', gap: 2 }}>
        <FormControl sx={{ minWidth: 300 }}>
          <InputLabel id="dashboard-select-label">Select Dashboard</InputLabel>
          <Select
            labelId="dashboard-select-label"
            id="dashboard-select"
            value={selectedDashboard}
            label="Select Dashboard"
            onChange={handleDashboardChange}
          >
            {dashboards.map((dashboard) => (
              <MenuItem key={dashboard.uid} value={dashboard.uid}>
                {dashboard.title}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        
        <Tooltip title="Open Grafana in new tab">
          <Box
            sx={{ display: 'flex', alignItems: 'center', gap: 0.5, cursor: 'pointer' }}
            onClick={() => window.open(`${grafanaUrl}/dashboards`, '_blank')}
          >
            <Typography variant="body2" sx={{ color: P.accentText }}>
              Grafana
            </Typography>
            <OpenInNew fontSize="small" color="primary" />
          </Box>
        </Tooltip>
      </Box>

      {/* Dashboard iframe */}
      <Box sx={{ flex: 1, overflow: 'hidden' }}>
        {selectedDashboardData && (
          <iframe
            src={withGrafanaWorkspace(`${grafanaUrl}/d/${selectedDashboardData.uid}/${selectedDashboardData.slug}?orgId=1&refresh=30s&theme=${actualMode}&kiosk`, activeWorkspace?.id)}
            width="100%"
            height="100%"
            frameBorder="0"
            title={selectedDashboardData.title}
            style={{
              border: 'none',
              display: 'block',
            }}
          />
        )}
      </Box>
    </Box>
  );
};

export default GrafanaDashboard;
