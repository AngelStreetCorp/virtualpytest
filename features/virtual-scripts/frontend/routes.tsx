/**
 * Virtual-scripts feature - frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled.
 *
 *   /builder/virtual-scripts  Virtual Scripts editor (Test › Build menu)
 */
import React from 'react';
import { Terminal as TerminalIcon } from '@mui/icons-material';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

const VirtualScripts = React.lazy(() => import('./VirtualScripts'));

const feature: FeatureDefinition = {
  routes: [
    // The editor has its own AI mode, so the global Ask AI button is redundant there.
    { path: '/builder/virtual-scripts', element: <VirtualScripts />, hideFloatingAiButton: true },
  ],
  nav: [
    {
      section: 'test-build',
      label: 'Virtual Scripts',
      path: '/builder/virtual-scripts',
      icon: <TerminalIcon fontSize="small" />,
    },
  ],
};

export default feature;
