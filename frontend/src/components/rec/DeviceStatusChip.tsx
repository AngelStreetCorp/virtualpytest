import { Box, SxProps, Theme, Tooltip, Typography, keyframes } from '@mui/material';
import React, { useMemo } from 'react';

import { useAgentChatPalette } from '../../constants/agentChatTheme';
import { Host } from '../../types/common/Host_Types';

interface DeviceStatusChipProps {
  host: Host;
  // True while a named script/deployment is driving this device.
  isRunning?: boolean;
  /** Optional deployment name to surface in the running-state tooltip. */
  deploymentName?: string | null;
  /**
   * The device's own link, for a device that joins on demand (a drone pairs over its
   * Wi-Fi AP). Unset for everything else. 'off' = not paired (grey), 'scanning' =
   * looking for / pairing it (pulsing yellow), 'on' = paired (normal colours).
   */
  link?: 'off' | 'scanning' | 'on';
  sx?: SxProps<Theme>;
}

const pulse = keyframes`
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
`;

/**
 * Status indicator used in the REC preview card header on device-control.
 *
 * Renders only a small colored dot — the verbose "online" / "running" / "error"
 * text used to live here, but on tight preview-card headers it crowded out the
 * Localize + AVQ buttons next to it. The full state text is still exposed via
 * the tooltip on hover.
 *
 * Colour logic mirrors the dot in `RecStreamModalHeader` so the same host reads
 * the same way in the grid and in the stream modal toolbar:
 *
 * - red  (`P.error`)      — any host service is stuck, OR host.status is offline / unknown
 * - blue (series[1])        — a script/deployment is currently driving the device
 * - green (custom green)  — host.status === 'online' and nothing else is wrong
 * - grey / pulsing yellow — host online but the device's own `link` is off / scanning
 *
 * The dot width is fixed so a row of preview cards has uniform alignment; we
 * keep flexShrink:0 on the wrapper so a long device name can ellipsize without
 * collapsing the dot.
 */
export const DeviceStatusChip: React.FC<DeviceStatusChipProps> = ({
  host,
  isRunning = false,
  deploymentName = null,
  link,
  sx,
}) => {
  const P = useAgentChatPalette();

  // Stuck services on the host outrank both the running script and host.status,
  // so a stuck host still shows red even when the host itself is flagged online.
  const stuckServices = useMemo(
    () => (host.system_stats?.service_health?.services ?? []).filter((s) => s.status === 'stuck'),
    [host.system_stats?.service_health?.services],
  );
  const isHostStuck = stuckServices.length > 0;
  const stuckServiceNames = stuckServices.map((s) => s.label || s.name).join(', ');

  // The device's own link only speaks once the host itself is fine.
  const linkDown = !isHostStuck && !isRunning && host.status === 'online' && link !== undefined && link !== 'on';
  const isScanning = linkDown && link === 'scanning';

  const dotColor = isHostStuck
    ? P.error // red when any host service is stuck
    : isRunning
      ? P.series[1] // blue while a script drives the device
      : host.status === 'online'
        ? linkDown
          ? isScanning
            ? P.warning // pulsing yellow while scanning / pairing
            : P.textMuted // grey: online, but the device is not paired
          : '#2ecc71' // green when the host is up
        : P.error; // red when offline / unknown

  const headline = isHostStuck
    ? 'Error — host services stuck'
    : isRunning
      ? `Running — ${deploymentName || 'script in progress'}`
      : host.status === 'online'
        ? linkDown
          ? isScanning
            ? 'Scanning for the device'
            : 'Not paired'
          : 'Online'
        : host.status === 'offline'
          ? 'Offline'
          : `Status: ${host.status}`;

  return (
    <Tooltip
      arrow
      placement="top"
      title={
        <Box sx={{ py: 0.25 }}>
          <Typography variant="caption" sx={{ display: 'block', fontWeight: 'bold' }}>
            {headline}
          </Typography>
          {isHostStuck && stuckServiceNames && (
            <Typography variant="caption" sx={{ display: 'block' }}>
              Stuck services: {stuckServiceNames}
            </Typography>
          )}
        </Box>
      }
    >
      {/* Same box that used to host the Chip — keeps its 24px width so the row
          geometry is stable, and renders just the dot in the middle. */}
      <Box
        aria-label={headline}
        role="status"
        sx={{
          width: 24,
          height: 20,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          ...sx,
        }}
      >
        <Box
          sx={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            backgroundColor: dotColor,
            ...(isScanning ? { animation: `${pulse} 1.2s ease-in-out infinite` } : {}),
            // Thin halo tinted by the card edge colour so the dot stays visible
            // on both the white (light) and dark-grey (dark) card surfaces.
            boxShadow: `0 0 0 1.5px ${P.borderColor}`,
          }}
        />
      </Box>
    </Tooltip>
  );
};
