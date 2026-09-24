import { Box, Tooltip } from '@mui/material';
import { SxProps, Theme } from '@mui/material/styles';
import React from 'react';

/**
 * Bottom-left overlay marking a preview whose device is not in our lab but leased
 * from a cloud device farm. Driven by `device.device_farm_provider`, which the host
 * only sets for a features/device-farm device — every local device renders nothing.
 *
 * Sits opposite RunningScriptNameBadge (bottom-right) so the two never overlap.
 */

const FARMS: Record<string, { label: string; logo: string }> = {
  browserstack: { label: 'BrowserStack', logo: '/vendor/farm/browserstack-mark.svg' },
  saucelabs: { label: 'Sauce Labs', logo: '/vendor/farm/saucelabs-mark.svg' },
};

interface DeviceFarmBadgeProps {
  /** Provider slug from the host ('browserstack', 'saucelabs', …). */
  provider?: string | null;
  sx?: SxProps<Theme>;
}

export const DeviceFarmBadge: React.FC<DeviceFarmBadgeProps> = ({ provider, sx }) => {
  const farm = provider ? FARMS[provider.toLowerCase()] : undefined;
  // A provider we have no mark for (lambdatest, or one added host-side later) gets no
  // badge rather than a wrong one — the device is still fully usable either way.
  if (!farm) {
    return null;
  }

  return (
    <Tooltip title={`Cloud device — ${farm.label}`} arrow placement="top">
      <Box
        sx={{
          position: 'absolute',
          left: 8,
          bottom: 8,
          zIndex: 3,
          display: 'flex',
          alignItems: 'center',
          px: 0.5,
          py: 0.4,
          borderRadius: 1,
          backgroundColor: 'rgba(0, 0, 0, 0.7)',
          pointerEvents: 'auto',
          ...sx,
        }}
      >
        <Box
          component="img"
          src={farm.logo}
          alt={farm.label}
          sx={{ height: 16, width: 'auto', display: 'block' }}
        />
      </Box>
    </Tooltip>
  );
};
