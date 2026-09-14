/**
 * AVQ feature - frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled.
 */
import React from 'react';
import { QueryStats as QualityIcon } from '@mui/icons-material';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

const AVQDevicePage = React.lazy(() => import('./AVQDevicePage'));

const avqDevicePath = (hostName: string, deviceId: string) =>
  `/monitoring/avq/${encodeURIComponent(hostName)}/${encodeURIComponent(deviceId)}`;

const feature: FeatureDefinition = {
  routes: [{ path: '/monitoring/avq/:hostName/:deviceId', element: <AVQDevicePage /> }],
  deviceLinks: [
    {
      label: 'Audio/Video Quality',
      icon: <QualityIcon sx={{ fontSize: 15 }} />,
      path: avqDevicePath,
    },
  ],
};

export default feature;
