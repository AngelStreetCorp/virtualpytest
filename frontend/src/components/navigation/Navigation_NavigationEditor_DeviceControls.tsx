import { Tv as TvIcon } from '@mui/icons-material';
import {
  Box,
  Button,
  CircularProgress,
} from '@mui/material';
import React from 'react';
import { TargetDropdown } from '../common/TargetDropdown';
import { DeviceKey } from '../../hooks/useDeviceFavorites';
import { getDeviceTargetLabel } from '../../hooks/useDeviceFilters';

import { NavigationEditorDeviceControlsProps } from '../../types/pages/NavigationHeader_Types';
import { TYPOGRAPHY } from '../../constants/typography';

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

  // Shared target list: one entry per device, labelled the same way as the Device Control filter.
  const targetOptions: string[] = [];
  const targetKeys: Record<string, DeviceKey> = {};
  availableHosts.forEach((host) =>
    (host.devices || []).forEach((device) => {
      const label = getDeviceTargetLabel(host, device);
      targetOptions.push(label);
      targetKeys[label] = { host_name: host.host_name, device_id: device.device_id };
    }),
  );
  const selectedTargetLabel =
    targetOptions.find(
      (label) => targetKeys[label].host_name === selectedHost?.host_name && targetKeys[label].device_id === selectedDeviceId,
    ) ?? '';

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
      {/* Target Selection Dropdown: shared with the Dashboard and Device Control filters (single-select here) */}
      <TargetDropdown
        multiple={false}
        width={180}
        isLocked={(label) => {
          const key = targetKeys[label];
          return !!key && isDeviceLocked(`${key.host_name}:${key.device_id}`);
        }}
        placeholder="Select Target..."
        selected={selectedTargetLabel ? [selectedTargetLabel] : []}
        options={targetOptions}
        keys={targetKeys}
        onChange={(next) => {
          const key = next[0] ? targetKeys[next[0]] : undefined;
          handleDeviceChange(key ? createDeviceKey(key.host_name, key.device_id) : '');
        }}
      />

      {middleContent}

      {/* Combined Take Control & Remote Panel Button */}
      <Button
        variant={isControlActive ? 'contained' : 'outlined'}
        size="small"
        onClick={onTakeControl}
        disabled={!selectedHost || !selectedDeviceId || isControlLoading || disableTakeControl}
        startIcon={
          // Same fixed slot for both icons so the spinner sits inside the button border.
          <Box
            component="span"
            sx={{ width: 16, height: 16, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
          >
            {isControlLoading ? <CircularProgress size={16} thickness={5} /> : <TvIcon />}
          </Box>
        }
        color={isControlActive ? 'success' : isSelectedDeviceLocked ? 'warning' : 'primary'}
        sx={{
          height: 32,
          fontSize: TYPOGRAPHY.caption.size,
          textTransform: 'none',
          width: 140, // fixed — fits "Processing..." plus the spinner inside the border
          minWidth: 140,
          maxWidth: 140,
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
