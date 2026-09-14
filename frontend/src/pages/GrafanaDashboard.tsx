import { Box, FormControl, InputLabel, MenuItem, Select, SelectChangeEvent, Tooltip, Typography } from '@mui/material';
import { OpenInNew } from '@mui/icons-material';
import React, { useState } from 'react';

interface Dashboard {
  title: string;
  uid: string;
  slug: string;
}

const GrafanaDashboard: React.FC = () => {
  // Get Grafana URL from environment variable
  const grafanaUrl = (import.meta as any).env?.VITE_GRAFANA_URL || 'http://localhost/grafana';

  // Available dashboards including System Monitoring
  const dashboards: Dashboard[] = [
    {
      title: 'Server Monitoring',
      uid: 'system-monitoring',
      slug: 'system-monitoring'
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
      title: 'FullZap Results',
      uid: 'f0fa93e1-e6a3-4a46-a374-6666a925952c',
      slug: 'fullzap-results'
    },
    {
      title: 'Navigation Metrics',
      uid: '9369e579-7f7a-47ec-ae06-f3a49e530b4f',
      slug: 'navigation-metrics'
    }
  ];

  // Default to System Monitoring
  const [selectedDashboard, setSelectedDashboard] = useState<string>('system-monitoring');

  const handleDashboardChange = (event: SelectChangeEvent<string>) => {
    setSelectedDashboard(event.target.value);
  };

  const selectedDashboardData = dashboards.find(d => d.uid === selectedDashboard);

  return (
    <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Dashboard Selector */}
      <Box sx={{ p: 2, borderBottom: '1px solid #e0e0e0', display: 'flex', alignItems: 'center', gap: 2 }}>
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
            <Typography variant="body2" color="primary">
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
            src={`${grafanaUrl}/d/${selectedDashboardData.uid}/${selectedDashboardData.slug}?orgId=1&refresh=30s&theme=light&kiosk`}
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
