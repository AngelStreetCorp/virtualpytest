/**
 * Live-TV companion feature - frontend entry (docs/technical/FEATURES.md).
 * Imported by the vpt-features Vite plugin only when the feature is enabled; it registers one
 * video overlay (the companion strip) through the core videoOverlays slot.
 */
import React from 'react';

import type { FeatureDefinition } from '../../../frontend/src/config/features';

import { CompanionStrip } from './CompanionStrip';
import { useCompanion } from './useCompanion';

/** The strip under the live video. Polls only while the player is Live with Monitoring on. */
const CompanionOverlay: React.FC<{ hostName: string; deviceId: string; isLiveMode: boolean; monitoringMode: boolean }> = ({
  hostName,
  deviceId,
  isLiveMode,
  monitoringMode,
}) => {
  const show = isLiveMode && monitoringMode;
  const companion = useCompanion(hostName, deviceId, show);
  return <CompanionStrip companion={companion ?? undefined} show={show} />;
};

const feature: FeatureDefinition = {
  videoOverlays: [{ Component: CompanionOverlay }],
};

export default feature;
