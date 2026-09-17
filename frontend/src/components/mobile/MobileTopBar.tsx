import { Box, Tab, Tabs } from '@mui/material';
import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

type RunNavSection = 'tests' | 'build' | 'deployments';

const getRunNavSection = (pathname: string): RunNavSection => {
  if (pathname.startsWith('/run/deployments') || pathname.startsWith('/test-execution/deployments')) return 'deployments';
  if (
    pathname.startsWith('/run/build') ||
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

/**
 * Mobile-only sub-navigation for switching between Tests / Build / Deployments
 * within the Run Execution area (/run/* and /test-execution/*).
 *
 * This used to be a secondary Tabs row rendered inside MobileTopBar's fixed
 * AppBar. The mobile top app bar (logo + theme toggle) was removed since the
 * bottom nav already provides navigation context, but this Tabs row is the
 * only way to reach these sub-views on mobile, so it's relocated inline at
 * the top of the Run Execution page content instead.
 */
const MobileRunNavTabs: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const runBasePath: '/run' | '/test-execution' = location.pathname.startsWith('/test-execution/')
    ? '/test-execution'
    : '/run';

  return (
    <Box sx={{ width: '100%', mb: 1 }}>
      <Tabs
        value={getRunNavSection(location.pathname)}
        onChange={(_, value: RunNavSection) => navigate(getRunNavPath(runBasePath, value))}
        variant="fullWidth"
        textColor="primary"
        indicatorColor="primary"
        sx={{ minHeight: 42, '& .MuiTab-root': { minHeight: 42, textTransform: 'none', fontSize: '0.8rem' } }}
      >
        <Tab label="Tests" value="tests" />
        <Tab label="Build" value="build" />
        <Tab label="Deployments" value="deployments" />
      </Tabs>
    </Box>
  );
};

export default MobileRunNavTabs;
