/**
 * GitLab feature — frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled, so with
 * DISABLED_FEATURES=gitlab neither page nor its identifiers reach the bundle.
 */
import { Code as GitLabIcon } from '@mui/icons-material';
import React from 'react';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

const GitLabPage = React.lazy(() => import('./GitLabPage'));

const feature: FeatureDefinition = {
  routes: [
    { path: '/monitoring/gitlab', element: <GitLabPage /> },
  ],
  nav: [
    {
      section: 'monitoring',
      label: 'GitLab',
      path: '/monitoring/gitlab',
      icon: <GitLabIcon fontSize="small" />,
    },
  ],
};

export default feature;
