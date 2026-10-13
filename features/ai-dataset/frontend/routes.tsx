/**
 * AI-dataset feature - frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled.
 *
 *   /training-review  AI Dataset page: human review of AI training samples + eval freeze
 *                     (TASK-27 step 4). Nav entry at the end of the AI dropdown.
 *
 * Admin only: the route renders under core's ProtectedRoute and the nav item goes through
 * isPathHidden; both look the path up in PAGE_PERMISSIONS ('/training-review' ->
 * 'ai.training:view', an ADMIN_ONLY permission), the same permission the
 * /server/training-samples routes require. No extra guard is needed here.
 */
import React from 'react';
import { FactCheck as AiDatasetIcon } from '@mui/icons-material';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

const TrainingReview = React.lazy(() => import('./TrainingReview'));

const feature: FeatureDefinition = {
  routes: [{ path: '/training-review', element: <TrainingReview /> }],
  nav: [
    {
      section: 'ai',
      label: 'AI Dataset',
      path: '/training-review',
      icon: <AiDatasetIcon fontSize="small" />,
    },
  ],
};

export default feature;
