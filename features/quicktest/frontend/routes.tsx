/**
 * QuickTest feature - frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled.
 */
import React from 'react';
import { FlashOn as QuickGuideIcon } from '@mui/icons-material';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

const QuickTestBuilder = React.lazy(() => import('./QuickTestBuilder'));

const feature: FeatureDefinition = {
  routes: [
    // The builder has its own device/AI chrome: hide the global Ask-AI button there.
    { path: '/builder/quick-test', element: <QuickTestBuilder />, hideFloatingAiButton: true },
  ],
  nav: [
    {
      section: 'test-build',
      label: 'QuickTest Builder',
      path: '/builder/quick-test',
      icon: <QuickGuideIcon fontSize="small" />,
    },
  ],
};

export default feature;
