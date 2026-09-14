/**
 * CI/CD feature — frontend entry (docs/technical/FEATURES.md, TASK-06 W4/W8).
 * Imported by the vpt-features Vite plugin only when the feature is enabled, so with
 * DISABLED_FEATURES=cicd neither page nor its identifiers reach the bundle.
 */
import { PlayCircleOutline as RunIcon, FactCheck as ReportIcon } from '@mui/icons-material';
import React from 'react';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

const CICDReportsPage = React.lazy(() => import('./CICDReportsPage'));
const RunCICDPage = React.lazy(() => import('./RunCICDPage'));

const feature: FeatureDefinition = {
  routes: [
    { path: '/test-results/cicd-reports', element: <CICDReportsPage /> },
    { path: '/test-execution/cicd', element: <RunCICDPage /> },
  ],
  nav: [
    {
      section: 'test-report',
      label: 'CI/CD Reports',
      path: '/test-results/cicd-reports',
      icon: <ReportIcon fontSize="small" />,
    },
    {
      section: 'test-execute',
      label: 'Run CI/CD',
      path: '/test-execution/cicd',
      icon: <RunIcon fontSize="small" />,
    },
  ],
};

export default feature;
