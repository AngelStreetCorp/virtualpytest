import {
  AppBar,
  Box,
  Tab,
  Tabs,
  Toolbar,
  Typography,
} from '@mui/material';
import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useBranding } from '../../contexts/BrandingContext';
import ThemeToggle from '../common/ThemeToggle';

type RunNavSection = 'tests' | 'build' | 'deployments';

const getRunNavSection = (pathname: string): RunNavSection => {
  if (pathname.startsWith('/run/deployments') || pathname.startsWith('/test-execution/deployments')) return 'deployments';
  if (
    pathname.startsWith('/run/build') ||
    pathname.startsWith('/test-execution/build-campaign') ||
    pathname.startsWith('/test-execution/build-campaign')
  ) return 'build';
  return 'tests';
};

const getRunNavPath = (basePath: '/run' | '/test-execution', section: RunNavSection): string => {
  if (basePath === '/test-execution') {
    if (section === 'tests') return '/test-execution/run-tests';
    if (section === 'build') return '/test-execution/build-campaign';
    return '/test-execution/deployments';
  }

  if (section === 'tests') return '/run/tests';
  if (section === 'build') return '/run/build';
  return '/run/deployments';
};

const MobileTopBar: React.FC = () => {
  const { branding } = useBranding();
  const location = useLocation();
  const navigate = useNavigate();
  const runBasePath: '/run' | '/test-execution' = location.pathname.startsWith('/test-execution/')
    ? '/test-execution'
    : '/run';

  const showRunTabs = location.pathname.startsWith('/run/') || location.pathname.startsWith('/test-execution/');

  return (
    <AppBar position="sticky" elevation={1}>
      <Toolbar sx={{ minHeight: 56, px: 1.25 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, flexGrow: 1 }}>
          {branding.logoUrl ? (
            <Box
              component="img"
              src={branding.logoUrl}
              alt={`${branding.name} logo`}
              sx={{ height: 22, width: 'auto', maxWidth: 120, objectFit: 'contain' }}
            />
          ) : null}
          {branding.showProjectName ? (
            <Typography variant="subtitle1" noWrap sx={{ fontWeight: 600 }}>
              {branding.name}
            </Typography>
          ) : null}
        </Box>

        <ThemeToggle />
      </Toolbar>

      {showRunTabs ? (
        <Tabs
          value={getRunNavSection(location.pathname)}
          onChange={(_, value: RunNavSection) => navigate(getRunNavPath(runBasePath, value))}
          variant="fullWidth"
          textColor="inherit"
          indicatorColor="secondary"
          sx={{ minHeight: 42, '& .MuiTab-root': { minHeight: 42, textTransform: 'none', fontSize: '0.8rem' } }}
        >
          <Tab label="Tests" value="tests" />
          <Tab label="Build" value="build" />
          <Tab label="Deployments" value="deployments" />
        </Tabs>
      ) : null}
    </AppBar>
  );
};

export default MobileTopBar;
