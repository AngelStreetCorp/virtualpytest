import { useState, useMemo, useEffect } from 'react';

import { Device } from '../../types/common/Host_Types';
import { DEFAULT_DEVICE_RESOLUTION } from '../../config/deviceResolutions';
import { isMobileModel } from '../../config/layoutConfig';

export interface StreamContainerDimensions {
  width: number;
  height: number;
  x: number;
  y: number;
}

/**
 * Computes REC modal stream container dimensions.
 */
export const useRecStreamLayout = (
  showRemote: boolean,
  showWeb: boolean,
  isDesktopDevice: boolean,
  isControlActive: boolean
): {
  finalStreamContainerDimensions: StreamContainerDimensions;
  scriptNameRightOffset: number | string;
} => {
  const [isWindowReady, setIsWindowReady] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setIsWindowReady(true);
    }
  }, []);

  const streamContainerDimensions = useMemo(() => {
    if (typeof window === 'undefined') {
      return { width: 0, height: 0, x: 0, y: 0 };
    }

    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;
    const modalWidth = windowWidth * 0.95;
    const modalHeight = windowHeight * 0.9;
    const headerMinHeight = 48;
    const headerPadding = 16;
    const actualHeaderHeight = headerMinHeight + headerPadding;

    const hasAnyPanel = showRemote || (showWeb && isDesktopDevice);
    const streamAreaWidth = hasAnyPanel ? modalWidth * 0.8 : modalWidth;
    const maxStreamAreaHeight = modalHeight - actualHeaderHeight;
    const targetAspectRatio = DEFAULT_DEVICE_RESOLUTION.height / DEFAULT_DEVICE_RESOLUTION.width;
    const idealStreamHeightFromAspect = streamAreaWidth * targetAspectRatio;
    const streamAreaHeight = Math.min(maxStreamAreaHeight, idealStreamHeightFromAspect);

    const modalX = (windowWidth - modalWidth) / 2;
    const modalY = (windowHeight - modalHeight) / 2;
    const streamX = modalX;
    const additionalOffset = -8;
    const streamY = modalY + actualHeaderHeight + additionalOffset;

    return {
      width: Math.round(streamAreaWidth),
      height: Math.round(streamAreaHeight),
      x: Math.round(streamX),
      y: Math.round(streamY),
    };
  }, [isDesktopDevice, showRemote, showWeb]);

  const finalStreamContainerDimensions = useMemo(() => {
    if (!isWindowReady || typeof window === 'undefined') {
      return { width: 0, height: 0, x: 0, y: 0 };
    }
    return streamContainerDimensions;
  }, [streamContainerDimensions, isWindowReady]);

  const scriptNameRightOffset = useMemo(() => {
    if (!isControlActive) return 8;
    const panelCount = (showRemote ? 1 : 0) + (showWeb && isDesktopDevice ? 1 : 0);
    if (panelCount === 0) return 8;
    return `calc(${panelCount * 20}% + 8px)`;
  }, [isControlActive, showRemote, showWeb, isDesktopDevice]);

  return {
    finalStreamContainerDimensions,
    scriptNameRightOffset,
  };
};

/**
 * Device model checks for REC components.
 */
export const useRecDeviceChecks = (device: Device | undefined) => {
  const isDesktopDevice = useMemo(
    () => device?.device_model === 'host_vnc',
    [device?.device_model]
  );

  const isMobile = useMemo(
    () => isMobileModel(device?.device_model),
    [device?.device_model]
  );

  const hasPowerControl = useMemo(() => {
    const capabilities = device?.device_capabilities;
    return capabilities && capabilities.power !== null && capabilities.power !== undefined;
  }, [device?.device_capabilities]);

  return { isDesktopDevice, isMobileModel: isMobile, hasPowerControl };
};
