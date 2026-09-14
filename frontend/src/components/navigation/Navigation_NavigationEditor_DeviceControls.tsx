import { Tv as TvIcon, Lock as LockIcon } from '@mui/icons-material';
import {
  Box,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  CircularProgress,
} from '@mui/material';
import React from 'react';

import { NavigationEditorDeviceControlsProps } from '../../types/pages/NavigationHeader_Types';

export const NavigationEditorDeviceControls: React.FC<NavigationEditorDeviceControlsProps> = ({
  selectedHost,
  selectedDeviceId,
  isControlActive,
  isControlLoading,
  availableHosts,
  isDeviceLocked,
  onDeviceSelect,
  onTakeControl,
  disableTakeControl = false, // Optional prop to disable Take Control button
  middleContent,
}) => {
  // Helper function to create a unique device identifier
  const createDeviceKey = (hostName: string, deviceId: string) => `${hostName}:${deviceId}`;

  // Helper function to parse device key back to components
  const parseDeviceKey = (key: string) => {
    const [hostName, deviceId] = key.split(':');
    return { hostName, deviceId };
  };

  // Get the current selected device key for the dropdown
  const selectedDeviceKey =
    selectedHost && selectedDeviceId
      ? createDeviceKey(selectedHost.host_name, selectedDeviceId)
      : '';

  // Check if the selected device is locked (device-based locking)
  const isSelectedDeviceLocked =
    selectedHost && selectedDeviceId
      ? isDeviceLocked(`${selectedHost.host_name}:${selectedDeviceId}`)
      : false;

  // Handle device selection change
  const handleDeviceChange = (deviceKey: string) => {
    if (!deviceKey) {
      onDeviceSelect(null, null);
      return;
    }

    const { hostName, deviceId } = parseDeviceKey(deviceKey);
    const host = availableHosts.find((h) => h.host_name === hostName);

    if (host) {
      // Verify device exists in host
      const device = host.devices?.find((d) => d.device_id === deviceId);
      if (device) {
        console.log(
          `[@component:DeviceControls] Selected device: ${device.device_name} on host ${host.host_name}`,
        );
        onDeviceSelect(host, deviceId);
      } else {
        console.error('[@component:DeviceControls] Device not found in host:', {
          hostName,
          deviceId,
          availableDevices: host.devices?.map((d) => d.device_id) || [],
        });
        onDeviceSelect(null, null);
      }
    } else {
      console.error('[@component:DeviceControls] Host not found:', { hostName });
      onDeviceSelect(null, null);
    }
  };

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-end',
        gap: 1,
        minWidth: 0,
      }}
    >
      {/* Target Selection Dropdown */}
      <FormControl size="small" sx={{ minWidth: 180 }}>
        <InputLabel id="device-select-label">Target</InputLabel>
        <Select
          labelId="device-select-label"
          value={selectedDeviceKey}
          onChange={(e) => handleDeviceChange(e.target.value)}
          label="Target"
          disabled={isControlLoading || isControlActive}
          sx={{ height: 32, fontSize: '0.75rem' }}
        >
          {/* Render hidden fallback option if selectedDeviceKey doesn't exist in availableHosts */}
          {selectedDeviceKey && !availableHosts.some((host) =>
            host.devices?.some((d) => createDeviceKey(host.host_name, d.device_id) === selectedDeviceKey)
          ) && (
            <MenuItem value={selectedDeviceKey} sx={{ display: 'none' }}>
              {selectedDeviceKey}
            </MenuItem>
          )}
          
          {availableHosts.flatMap((host, hostIndex) => {
            const devices = host.devices || [];

            // Skip hosts with no devices
            if (devices.length === 0) {
              return [];
            }

            // Show all devices in a flat list with visual gaps between host groups
            return devices.map((device, deviceIndex) => {
              const deviceKey = createDeviceKey(host.host_name, device.device_id);
              const deviceIsLocked = isDeviceLocked(deviceKey);
              const isLastDeviceInHost = deviceIndex === devices.length - 1;
              const isNotLastHost = hostIndex < availableHosts.length - 1;

              return (
                <MenuItem
                  key={deviceKey}
                  value={deviceKey}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    opacity: deviceIsLocked ? 0.85 : 1,
                    borderBottom: isLastDeviceInHost && isNotLastHost ? '1px solid' : 'none',
                    borderColor: 'divider',
                    mb: isLastDeviceInHost && isNotLastHost ? 0.5 : 0,
                    pb: isLastDeviceInHost && isNotLastHost ? 0.5 : undefined,
                  }}
                >
                  {deviceIsLocked && (
                    <LockIcon sx={{ fontSize: '0.8rem', color: 'warning.main' }} />
                  )}
                  <span>
                    {(device.device_name || device.device_id).replace(/_Host$/, '')} ({host.host_name})
                  </span>
                  {deviceIsLocked && (
                    <Typography
                      variant="caption"
                      sx={{
                        ml: 'auto',
                        color: 'warning.main',
                        fontSize: '0.65rem',
                      }}
                    >
                      (Locked)
                    </Typography>
                  )}
                </MenuItem>
              );
            });
          })}
        </Select>
      </FormControl>

      {middleContent}

      {/* Combined Take Control & Remote Panel Button */}
      <Button
        variant={isControlActive ? 'contained' : 'outlined'}
        size="small"
        onClick={onTakeControl}
        disabled={!selectedHost || !selectedDeviceId || isControlLoading || disableTakeControl}
        startIcon={isControlLoading ? <CircularProgress size={16} /> : <TvIcon />}
        color={isControlActive ? 'success' : isSelectedDeviceLocked ? 'warning' : 'primary'}
        sx={{
          height: 32,
          fontSize: '0.75rem',
          textTransform: 'none',
          minWidth: 110,
          maxWidth: 110,
          whiteSpace: 'nowrap',
          px: 1.5,
        }}
        title={
          isControlLoading
            ? 'Processing...'
            : disableTakeControl
              ? 'Select a userinterface first to build navigation cache'
              : isSelectedDeviceLocked
                ? 'Device is locked; click to request takeover'
                : isControlActive
                  ? 'Release Control'
                  : 'Take Control'
        }
      >
        {isControlLoading
          ? 'Processing...'
          : isControlActive
            ? 'Release'
            : isSelectedDeviceLocked
              ? 'Take Over'
              : 'Control'}
      </Button>
    </Box>
  );
};

export default NavigationEditorDeviceControls;
