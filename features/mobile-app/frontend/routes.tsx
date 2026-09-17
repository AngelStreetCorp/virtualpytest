/**
 * mobile-app feature — frontend entry (docs/tasks/TASK-17-mobile-app-phone-agent.md §3, §4).
 * Imported by the vpt-features Vite plugin only when the feature is enabled, so with
 * DISABLED_FEATURES=mobile-app neither page nor its identifiers reach the bundle.
 */
import { PhoneAndroid as PhoneIcon } from '@mui/icons-material';
import React from 'react';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

import PhoneSlotPreviewAction from './PhoneSlotPreviewAction';
import { usePhoneTargetReadiness } from './usePhoneTargetReadiness';

const MobileAppPage = React.lazy(() => import('./MobileAppPage'));
const ThisPhonePage = React.lazy(() => import('./ThisPhonePage'));

const feature: FeatureDefinition = {
  routes: [
    { path: '/configuration/mobile-app', element: <MobileAppPage /> },
    // Native-only page (mockup §4); harmless on the web — see ThisPhonePage.tsx.
    { path: '/mobile-app/this-phone', element: <ThisPhonePage /> },
  ],
  // Clicking an unpaired phone slot's REC card opens its pairing code instead of a
  // full-screen "phone offline" placeholder. See PhoneSlotPreviewAction.
  previewActions: [{ deviceModel: 'phone_agent', Component: PhoneSlotPreviewAction }],
  // Run Tests offers a phone slot whether or not a phone is behind it; this says when one
  // really is there and streaming. See usePhoneTargetReadiness.
  targetReadiness: [{ deviceModel: 'phone_agent', useReadiness: usePhoneTargetReadiness }],
  nav: [
    {
      section: 'settings',
      label: 'Mobile App',
      path: '/configuration/mobile-app',
      icon: <PhoneIcon fontSize="small" />,
    },
  ],
};

export default feature;
