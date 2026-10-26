/**
 * mods feature — frontend entry (docs/agent/platform/MODS.md, TASK-77).
 * Imported by the vpt-features Vite plugin only when the feature is enabled; with
 * DISABLED_FEATURES=mods no mod loads and the Mods page is gone.
 */
import { Extension as ModsIcon } from '@mui/icons-material';
import React from 'react';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

import { blastRadiusMod } from './blastRadius/register';
import { infoTilesMod } from './infoTiles/register';
import { onlineUsersMod } from './onlineUsers/register';
import { pipMod } from './pip/register';
import { runProgressMod } from './runProgress/register';
import { splitViewMod } from './splitView/register';
import { teamDevicesMod } from './teamDevices/register';

const ModsPage = React.lazy(() => import('./manager/ModsPage'));

const feature: FeatureDefinition = {
  routes: [{ path: '/configuration/mods', element: <ModsPage /> }],
  nav: [
    {
      section: 'settings',
      label: 'Mods',
      path: '/configuration/mods',
      icon: <ModsIcon fontSize="small" />,
    },
  ],
  // Order = chain order: the first mod runs first.
  mods: [runProgressMod, blastRadiusMod, onlineUsersMod, pipMod, splitViewMod, teamDevicesMod, infoTilesMod],
};

export default feature;
