/**
 * Controller Configuration Hook - Minimal Implementation
 */

import {
  ControllerConfigMap,
  ControllerConfiguration,
} from '../../types/controller/Controller_Types';

const baseConfiguration = {
  description: '',
  status: 'available' as const,
  inputFields: [] as any[],
};

const createConfiguration = (
  id: string,
  name: string,
  implementation: string,
): ControllerConfiguration => ({
  id,
  name,
  implementation,
  ...baseConfiguration,
});

// Minimal controller configurations - only what's actually used
const CONTROLLER_CONFIGURATIONS: ControllerConfigMap = {
  remote: [
    createConfiguration('android_tv', 'Android TV', 'android_tv'),
    createConfiguration('android_mobile', 'Android Mobile', 'android_mobile'),
    createConfiguration('appium_remote', 'Appium Remote', 'appium_remote'),
  ],
  av: [
    createConfiguration('hdmi_stream', 'HDMI Stream', 'hdmi_stream'),
    createConfiguration('vnc_stream', 'VNC Stream', 'vnc_stream'),
  ],
  verification: [
    createConfiguration('image', 'Image', 'image'),
    createConfiguration('text', 'Text', 'text'),
    createConfiguration('appium', 'Appium', 'appium'),
  ],
  network: [],
  power: [createConfiguration('tapo', 'Tapo Power', 'tapo')],
};

export const useControllerConfig = () => {
  const getConfigurationsByType = (type: keyof ControllerConfigMap): ControllerConfiguration[] => {
    return CONTROLLER_CONFIGURATIONS[type] || [];
  };

  const getConfigurationByImplementation = (
    type: keyof ControllerConfigMap,
    implementation: string,
  ): ControllerConfiguration | null => {
    const typeConfigs = CONTROLLER_CONFIGURATIONS[type] || [];
    return typeConfigs.find((config) => config.implementation === implementation) || null;
  };

  const validateParameters = (
    _type: keyof ControllerConfigMap,
    implementation: string,
    _parameters: { [key: string]: any },
  ): { isValid: boolean; errors: string[] } => {
    return implementation
      ? { isValid: true, errors: [] }
      : { isValid: false, errors: ['No implementation'] };
  };

  return {
    getConfigurationsByType,
    getConfigurationByImplementation,
    validateParameters,
  };
};
