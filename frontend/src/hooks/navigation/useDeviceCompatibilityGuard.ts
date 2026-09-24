import { useEffect } from 'react';

import { getCompatibleModels } from '../../config/deviceModelFamilies';

const LOG_PREFIX = '[@useDeviceCompatibilityGuard]';

interface UseDeviceCompatibilityGuardProps {
  userInterface: { name: string; models?: string[] } | null;
  selectedHost: any;
  selectedDeviceId: string | null;
  isControlActive: boolean;
  onReleaseControl: () => void;
  onClearSelection: () => void;
}

/**
 * Hook to guard against incompatible device selections when switching userinterfaces.
 * 
 * When navigating between userinterfaces with different device model requirements,
 * this hook automatically releases control and clears the device selection if the
 * currently selected device is not compatible with the new interface.
 * 
 * Example:
 * - User has host_vnc device selected on a web interface
 * - User navigates to android_mobile interface
 * - Hook detects incompatibility and auto-releases + clears selection
 */
export const useDeviceCompatibilityGuard = ({
  userInterface,
  selectedHost,
  selectedDeviceId,
  isControlActive,
  onReleaseControl,
  onClearSelection,
}: UseDeviceCompatibilityGuardProps) => {
  useEffect(() => {
    // Skip if no interface or device selected
    if (!userInterface || !selectedHost || !selectedDeviceId) return;

    // Find the selected device
    const selectedDevice = selectedHost.devices?.find((d: any) => d.device_id === selectedDeviceId);
    if (!selectedDevice) return;

    const interfaceModels = userInterface.models || [];
    const deviceModel = selectedDevice.device_model;
    
    // Get compatible interface models for this device — its whole family, so a paired
    // phone or a cloud farm phone keeps an `android_mobile` interface selected
    // (config/deviceModelFamilies.ts, the one table every matcher reads)
    const compatibleInterfaceModels = getCompatibleModels(deviceModel);
    
    // Check if device is compatible with any of the interface's models
    const isCompatible = interfaceModels.some((model: string) => 
      compatibleInterfaceModels.includes(model)
    );

    if (!isCompatible) {
      console.log(
        `${LOG_PREFIX} Device ${selectedHost.host_name}:${selectedDeviceId} (${deviceModel}) ` +
        `is NOT compatible with interface ${userInterface.name} (models: ${interfaceModels.join(', ')}). ` +
        `Device supports: ${compatibleInterfaceModels.join(', ')}`
      );
      if (isControlActive) {
        console.log(`${LOG_PREFIX} Auto-releasing incompatible device`);
        onReleaseControl();
      }
      console.log(`${LOG_PREFIX} Clearing incompatible device selection`);
      onClearSelection();
    }
  }, [
    userInterface,
    selectedHost,
    selectedDeviceId,
    isControlActive,
    onReleaseControl,
    onClearSelection,
  ]);
};

