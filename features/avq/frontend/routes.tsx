/**
 * AVQ feature - frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled.
 */
import React from 'react';

import type { FeatureDefinition } from '../../../frontend/src/config/features';
import { AvqActivityIcon as QualityIcon } from '../../../frontend/src/components/common/icons/CustomIcons';

const AVQDevicePage = React.lazy(() => import('./AVQDevicePage'));

const avqDevicePath = (hostName: string, deviceId: string) =>
  `/monitoring/avq/${encodeURIComponent(hostName)}/${encodeURIComponent(deviceId)}`;

const feature: FeatureDefinition = {
  routes: [{ path: '/monitoring/avq/:hostName/:deviceId', element: <AVQDevicePage /> }],
  deviceLinks: [
    {
      label: 'Audio/Video Quality',
      icon: <QualityIcon fontSize="medium" />,
      path: avqDevicePath,
    },
  ],
};

export default feature;
