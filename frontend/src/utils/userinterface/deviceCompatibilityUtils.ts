/**
 * Device-Interface Compatibility Utilities
 * 
 * Shared logic for checking if devices are compatible with user interfaces
 * based on exact model matches or device capabilities.
 */

import { Device } from '../../types/common/Host_Types';

export interface UserInterface {
  id: string;
  name: string;
  models?: string[];
  root_tree?: string | { id: string; name: string } | null; // Support both old string format and new object format
  [key: string]: any;
}

/**
 * Check if a device is compatible with a user interface.
 * 
 * Compatibility is determined by:
 * 1. Exact model match: device.device_model is in userInterface.models
 * 2. Capability match: device has a capability matching one of the userInterface.models
 *    (e.g., userInterface with model 'desktop' matches device with desktop: true capability)
 * 
 * @param device - Device to check
 * @param userInterface - UserInterface to check against
 * @returns true if device is compatible with the interface
 */
export const isDeviceCompatibleWithInterface = (
  device: Device,
  userInterface: UserInterface
): boolean => {
  if (!userInterface.models || userInterface.models.length === 0) {
    return false;
  }

  const deviceModel = device.device_model;
  const deviceCapabilities = device.device_capabilities;

  // Check exact model match first
  if (userInterface.models.includes(deviceModel)) {
    return true;
  }

  // Check capability match - if userInterface model is 'web' or 'desktop', 
  // match devices that have those capabilities
  return userInterface.models.some((model) => 
    deviceCapabilities && (deviceCapabilities as any)[model]
  );
};

/**
 * Filter user interfaces to only those compatible with a specific device.
 * Only includes interfaces that have a root_tree configured.
 * 
 * @param interfaces - Array of user interfaces to filter
 * @param device - Device to check compatibility against
 * @returns Array of compatible user interfaces
 */
export const filterCompatibleInterfaces = (
  interfaces: UserInterface[],
  device: Device
): UserInterface[] => {
  return interfaces.filter((ui) => {
    // Check root_tree: support both string and object formats
    const hasTree = ui.root_tree ? (typeof ui.root_tree === 'string' ? !!ui.root_tree : !!ui.root_tree.id) : false;
    const isCompatible = isDeviceCompatibleWithInterface(device, ui);
    return hasTree && isCompatible;
  });
};

/**
 * Check if a host has at least one device compatible with the user interface.
 * Used for filtering hosts in the UI.
 * 
 * @param hostDevices - Array of devices from a host
 * @param userInterface - UserInterface to check against
 * @returns true if at least one device is compatible
 */
export const hasCompatibleDevice = (
  hostDevices: Device[],
  userInterface: UserInterface
): boolean => {
  if (!hostDevices || hostDevices.length === 0) {
    return false;
  }

  return hostDevices.some((device) => 
    isDeviceCompatibleWithInterface(device, userInterface)
  );
};

