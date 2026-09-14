/**
 * Device Resolution Constants
 * 
 * Single centralized resolution for all devices.
 * One resolution to rule them all.
 */

// ONE centralized resolution for everything
export const DEFAULT_DEVICE_RESOLUTION = { width: 1280, height: 720 } as const;

export type DeviceResolution = typeof DEFAULT_DEVICE_RESOLUTION;

// Simple function - always returns the same resolution
export const getDeviceResolution = (): DeviceResolution => {
  return DEFAULT_DEVICE_RESOLUTION;
};
