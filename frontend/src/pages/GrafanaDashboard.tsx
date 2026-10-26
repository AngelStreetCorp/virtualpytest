import { Box, Button, FormControl, InputLabel, MenuItem, Paper, Select, SelectChangeEvent, Tooltip, Typography } from '@mui/material';
import { OpenInNew } from '@mui/icons-material';
import React, { useCallback, useEffect, useState } from 'react';
import { getEnv } from '../config/constants';
import { useWorkspaceContext } from '../contexts/workspace/WorkspaceContext';
import { withGrafanaWorkspace } from '../utils/grafanaUrl';
import { GRAFANA_DASHBOARDS as allDashboards } from '../utils/grafanaDashboards';
import { useAgentChatPalette } from '../constants/agentChatTheme';
import { TYPOGRAPHY } from '../constants/typography';
import { useTheme } from '../contexts/ThemeContext';
import { apiClient } from '../utils/apiClient';
import { neutralButtonSx, primaryButtonSx } from '../components/common/PageChrome';

/**
 * What the Grafana probe answered:
 *  - 'checking'      the probe is in flight
 *  - 'signed-in'     the browser has a Grafana session — the embed works and the
 *                    search lists the dashboards this viewer may open
 *  - 'needs-sign-in' Grafana answered 401. Embedding the dashboard now would put
 *                    Grafana's own login form inside the app (BUG-0772), so the
 *                    page explains the state instead of embedding it.
 *  - 'unreachable'   Grafana did not answer at all
 *  - 'unknown'       Grafana answered something else (the embed may still work)
 */
type GrafanaSession = 'checking' | 'signed-in' | 'needs-sign-in' | 'unreachable' | 'unknown';

const GrafanaDashboard: React.FC = () => {
  const P = useAgentChatPalette();
  // Grafana follows the app theme (it was always light, a white block in dark mode).
  const { actualMode } = useTheme();
  const { activeWorkspace } = useWorkspaceContext();
  // Get Grafana URL from environment variable
  const grafanaUrl = getEnv('VITE_GRAFANA_URL') || 'http://localhost/grafana';

  // Open on Script Results: Server Monitoring is about the platform's own server, and a viewer
  // without access to it landed on a 403 "Failed to load dashboard" on first open.
  const [selectedDashboard, setSelectedDashboard] = useState<string>('2a3b060a-7820-4a6e-aa2a-adcbf5408bd3');

  // Grafana's search returns only the dashboards this viewer may open; list just those so nobody
  // picks one that ends in a 403. If the search cannot be reached (other host, no session), keep
  // the full list.
  const [visibleUids, setVisibleUids] = useState<Set<string> | null>(null);
  const [session, setSession] = useState<GrafanaSession>('checking');

  // Grafana keeps its own session, and the proxy in front of it injects no credentials, so the
  // app cannot pre-authenticate it. The page asks Grafana first and shows what it answers: a 401
  // means "sign in", and an iframe at that moment would only show Grafana's login form inside
  // the app (BUG-0772).
  const probeGrafana = useCallback(async () => {
    setSession('checking');
    try {
      // apiClient, not a raw fetch: it is the sanctioned wrapper. skipAuth keeps the
      // app's own JWT away from a Grafana that may live on another host; the session
      // cookie is what Grafana answers with.
      const res = await apiClient(`${grafanaUrl}/api/search?type=dash-db&limit=5000`, {
        credentials: 'include',
        skipAuth: true,
      });
      if (res.status === 401) {
        setVisibleUids(null);
        setSession('needs-sign-in');
        return;
      }
      if (!res.ok) {
        setSession('unknown');
        return;
      }
      const rows: Array<{ uid: string }> = await res.json();
      if (!Array.isArray(rows)) {
        setSession('unknown');
        return;
      }
      setVisibleUids(new Set(rows.map((r) => r.uid)));
      setSession('signed-in');
    } catch {
      setSession('unreachable');
    }
  }, [grafanaUrl]);

  useEffect(() => {
    void probeGrafana();
  }, [probeGrafana]);

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

  // Grafana cannot be embedded until the viewer has signed in to it, and the list of dashboards
  // is only truthful once Grafana has answered. Until then the page says so, instead of showing
  // a login form (or a picker of dashboards that cannot open).
  const needsSignIn = session === 'needs-sign-in';
  const unreachable = session === 'unreachable';
  const showPicker = !needsSignIn && !unreachable && dashboards.length > 0;
  const embeddable = !needsSignIn && !unreachable && Boolean(selectedDashboardData);

  const message = (
    heading: string,
    body: string,
    actions?: React.ReactNode,
  ) => (
    <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', p: 3 }}>
      <Paper variant="outlined" sx={{ maxWidth: 520, p: 3, textAlign: 'center' }}>
        <Typography sx={{ fontSize: TYPOGRAPHY.dialogTitle.size, fontWeight: TYPOGRAPHY.dialogTitle.weight, mb: 1 }}>
          {heading}
        </Typography>
        <Typography variant="body2" sx={{ color: P.textSecondary, mb: actions ? 2 : 0 }}>
          {body}
        </Typography>
        {actions && (
          <Box sx={{ display: 'flex', gap: 1, justifyContent: 'center', flexWrap: 'wrap' }}>
            {actions}
          </Box>
        )}
      </Paper>
    </Box>
  );

  return (
    // Fill the app's content area, not the viewport: this page already sits below the
    // AppHeader inside the app scroll container, so 100vh overflowed it and added a
    // second scrollbar next to the one Grafana draws inside the iframe.
    <Box sx={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {/* Dashboard Selector */}
      <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: P.borderColor, display: 'flex', alignItems: 'center', gap: 2 }}>
        {showPicker && (
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
        )}

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

      {/* Dashboard iframe — or the reason it is not there */}
      <Box sx={{ flex: 1, overflow: 'hidden' }}>
        {embeddable && selectedDashboardData && (
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

        {needsSignIn && message(
          'Grafana asks for a sign-in',
          'Grafana does not share the app’s session. Sign in to Grafana once in a new tab — the dashboards then open here, inside the app.',
          <>
            <Button variant="contained" sx={primaryButtonSx(P)} onClick={() => window.open(`${grafanaUrl}/login`, '_blank')}>
              Open Grafana to sign in
            </Button>
            <Button variant="outlined" sx={neutralButtonSx(P)} onClick={() => void probeGrafana()}>
              Check again
            </Button>
          </>,
        )}

        {unreachable && message(
          'Grafana did not answer',
          'The Grafana server is not reachable. Check that it is running, then try again.',
          <Button variant="contained" sx={primaryButtonSx(P)} onClick={() => void probeGrafana()}>
            Check again
          </Button>,
        )}

        {session === 'signed-in' && !embeddable && message(
          'No dashboard here',
          'Your account may open no dashboard on this Grafana yet.',
        )}

        {session === 'checking' && (
          <Box sx={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', p: 3 }}>
            <Typography variant="body2" sx={{ color: P.textMuted }}>
              Loading dashboards…
            </Typography>
          </Box>
        )}
      </Box>
    </Box>
  );
};

export default GrafanaDashboard;
