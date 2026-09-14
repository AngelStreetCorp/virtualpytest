import {
  Dashboard as DashboardIcon,
  Devices as DevicesIcon,
  PlayArrow as PlayArrowIcon,
  GridView as GridViewIcon,
  Settings as SettingsIcon,
} from '@mui/icons-material';
import { BottomNavigation, BottomNavigationAction, Paper } from '@mui/material';
import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useResponsiveMode } from '../../hooks/useResponsiveMode';

const resolveTabValue = (pathname: string): string => {
  if (pathname.startsWith('/run/') || pathname.startsWith('/test-execution/')) return '/run/tests';
  if (pathname.startsWith('/monitoring/heatmap')) return '/monitoring/heatmap';
  if (pathname.startsWith('/device-control')) return '/device-control';
  if (pathname.startsWith('/configuration/interface') || pathname.startsWith('/configuration/settings')) return '/configuration/interface';
  return '/';
};

const MobileBottomNav: React.FC = () => {
  const { isMobile } = useResponsiveMode();
  const location = useLocation();
  const navigate = useNavigate();

  const isAuthPage = location.pathname === '/login' || location.pathname === '/auth/callback';
  const isHiddenRoute = location.pathname.startsWith('/ai-agent');

  if (!isMobile || isAuthPage || isHiddenRoute) {
    return null;
  }

  return (
    <Paper
      elevation={8}
      sx={{
        position: 'fixed',
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 1200,
        borderTop: '1px solid',
        borderColor: 'divider',
      }}
    >
      <BottomNavigation
        value={resolveTabValue(location.pathname)}
        onChange={(_, value: string) => navigate(value)}
        showLabels
      >
        <BottomNavigationAction label="Dashboard" value="/" icon={<DashboardIcon />} />
        <BottomNavigationAction label="Device" value="/device-control" icon={<DevicesIcon />} />
        <BottomNavigationAction label="Run" value="/run/tests" icon={<PlayArrowIcon />} />
        <BottomNavigationAction label="Heatmap" value="/monitoring/heatmap" icon={<GridViewIcon />} />
        <BottomNavigationAction label="Settings" value="/configuration/interface" icon={<SettingsIcon />} />
      </BottomNavigation>
    </Paper>
  );
};

export default MobileBottomNav;
