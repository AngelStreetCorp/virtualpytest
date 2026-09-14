import { Chip, Tooltip } from '@mui/material';
import React from 'react';

interface FingerprintBadgeProps {
  hasScreenshot: boolean;
  hasFingerprint: boolean;
  region?: number[];
  /** Calibration: nodes this region can't be told apart from (from evaluate_region). */
  confusable?: string[];
  size?: 'small' | 'medium';
}

/** At-a-glance Localize status: fingerprint OK / region collides / screenshot-only / none. */
export const FingerprintBadge: React.FC<FingerprintBadgeProps> = ({
  hasScreenshot,
  hasFingerprint,
  region,
  confusable,
  size = 'small',
}) => {
  // Non-discriminative region: a wrong node hashes as close as this node's own
  // drift → amber warning so the author draws a tighter region.
  if (hasFingerprint && confusable && confusable.length > 0) {
    return (
      <Tooltip title={`Region not discriminative — collides with: ${confusable.slice(0, 6).join(', ')}. Draw a tighter region.`}>
        <Chip label={`⚠ region collides (${confusable.length})`} size={size} color="warning"
          sx={{ fontSize: '0.7rem', height: 20 }} />
      </Tooltip>
    );
  }
  if (!hasScreenshot) {
    return (
      <Tooltip title="No screenshot — capture one to enable Localize">
        <Chip label="– no screenshot" size={size} variant="outlined" sx={{ fontSize: '0.7rem', height: 20 }} />
      </Tooltip>
    );
  }
  if (!hasFingerprint) {
    return (
      <Tooltip title="Screenshot present, but no Localize fingerprint yet — set a region">
        <Chip label="○ no fingerprint" size={size} color="default"
          sx={{ fontSize: '0.7rem', height: 20, bgcolor: 'grey.300' }} />
      </Tooltip>
    );
  }
  const isFull = !region || JSON.stringify(region) === JSON.stringify([0, 1, 0, 1]);
  return (
    <Tooltip title={`Localize fingerprint set — region: ${isFull ? 'full frame' : JSON.stringify(region)}`}>
      <Chip label={`✓ fingerprint${isFull ? '' : ' (region)'}`} size={size} color="success"
        sx={{ fontSize: '0.7rem', height: 20 }} />
    </Tooltip>
  );
};

export default FingerprintBadge;
