import { Chip, SxProps, Theme } from '@mui/material';
import React, { useMemo } from 'react';

import { Host } from '../../types/common/Host_Types';

interface DeviceStatusChipProps {
  host: Host;
  // True while a named script/deployment is driving this device.
  isRunning?: boolean;
  sx?: SxProps<Theme>;
}

/**
 * Host/device status chip, shared by the preview card and the stream modal header.
 *
 * Blue while a script is driving this device: "online" is true the whole time either
 * way, so green said nothing about the one state where it matters whether you touch
 * the device or leave it alone. A stuck host still wins — that is a fault, not an
 * activity.
 */
export const DeviceStatusChip: React.FC<DeviceStatusChipProps> = ({
  host,
  isRunning = false,
  sx,
}) => {
  // Stuck services on the host outrank both the running script and host.status.
  const isHostStuck = useMemo(() => {
    const services = host.system_stats?.service_health?.services;
    if (!services) return false;
    return services.some((s) => s.status === 'stuck');
  }, [host.system_stats?.service_health?.services]);

  const color = isHostStuck
    ? 'error'
    : isRunning
      ? 'info'
      : host.status === 'online'
        ? 'success'
        : host.status === 'offline'
          ? 'error'
          : 'default';

  return (
    <Chip
      label={isHostStuck ? 'error' : isRunning ? 'running' : host.status}
      size="small"
      color={color}
      sx={{ fontSize: '0.7rem', height: 20, flexShrink: 0, ...sx }}
    />
  );
};
