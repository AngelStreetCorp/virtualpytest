/**
 * GitLab feature — frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled, so with
 * DISABLED_FEATURES=gitlab neither page nor its identifiers reach the bundle.
 */
import React from 'react';

import type { FeatureDefinition } from '../../../frontend/src/config/features';
import { GitLabMark } from './GitLabMark';

const GitLabPage = React.lazy(() => import('./GitLabPage'));

const feature: FeatureDefinition = {
  routes: [
    { path: '/monitoring/gitlab', element: <GitLabPage /> },
  ],
  nav: [
    {
      // Plugins, not Monitoring: GitLab is a third-party integration VPT connects to, and
      // that is what the Plugins dropdown is — Monitoring is the platform's own telemetry.
      section: 'plugins',
      label: 'GitLab',
      path: '/monitoring/gitlab',
      // The real GitLab mark, not a generic code glyph: this row is a link to GitLab, and the
      // mark inherits the row's colour like every other nav icon.
      icon: <GitLabMark fontSize={20} />,
    },
  ],
};

export default feature;
