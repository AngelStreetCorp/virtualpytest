/**
 * AI-test feature - frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled.
 *
 *   /test-prompt  Test Prompt page (full width, like /ai-agent)
 * The Virtual Scripts editor is its own feature (features/virtual-scripts).
 */
import React from 'react';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

const TestPrompt = React.lazy(() => import('./TestPrompt'));

const feature: FeatureDefinition = {
  routes: [{ path: '/test-prompt', element: <TestPrompt />, fullWidth: true }],
};

export default feature;
