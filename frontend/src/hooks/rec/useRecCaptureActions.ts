import { useState, useCallback } from 'react';

import { useToast } from '../useToast';
import { Host, Device } from '../../types/common/Host_Types';
import { buildServerUrl, getCaptureUrlFromStream } from '../../utils/buildUrlUtils';

export interface RecCaptureActionsState {
  capturedImageUrl: string | null;
  isImageQueryVisible: boolean;
}

export interface RecCaptureActionsActions {
  handleScreenshot: () => Promise<void>;
  handleAIImageQuery: () => Promise<void>;
  closeImageQuery: () => void;
}

/**
 * Manages REC modal capture actions (screenshot, AI image query).
 * Requires currentSegmentUrl for HLS devices; uses direct API for VNC.
 */
export const useRecCaptureActions = (
  host: Host,
  device: Device | undefined,
  currentSegmentUrl: string | null,
  isLiveMode: boolean,
  restartMode: boolean
): RecCaptureActionsState & RecCaptureActionsActions => {
  const [capturedImageUrl, setCapturedImageUrl] = useState<string | null>(null);
  const [isImageQueryVisible, setIsImageQueryVisible] = useState(false);
  const { showError } = useToast();

  const closeImageQuery = useCallback(() => {
    setIsImageQueryVisible(false);
  }, []);

  const handleScreenshot = useCallback(async () => {
    if (!isLiveMode || restartMode) {
      showError('Screenshot is only available in Live mode');
      return;
    }

    const isVncDevice = device?.device_model === 'host_vnc';
    if (isVncDevice && device) {
      try {
        const response = await fetch(buildServerUrl('/server/av/takeScreenshot'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            host_name: host.host_name,
            device_id: device.device_id,
          }),
        });
        if (!response.ok) {
          showError('Failed to take screenshot');
          return;
        }
        const result = await response.json();
        if (result.success && result.screenshot_url) {
          window.open(result.screenshot_url, '_blank');
        } else {
          showError('Failed to take screenshot');
        }
      } catch {
        showError('Failed to take screenshot');
      }
      return;
    }

    if (!currentSegmentUrl) {
      showError('Failed to take screenshot (video segment missing)');
      return;
    }

    const captureUrl = await getCaptureUrlFromStream(currentSegmentUrl, device ?? undefined, host);
    if (captureUrl) {
      window.open(captureUrl, '_blank');
    } else {
      showError('Could not determine current frame');
    }
  }, [host, device, currentSegmentUrl, isLiveMode, restartMode, showError]);

  const handleAIImageQuery = useCallback(async () => {
    if (!isLiveMode || restartMode) return;

    const isVncDevice = device?.device_model === 'host_vnc';
    if (isVncDevice && device) {
      try {
        const response = await fetch(buildServerUrl('/server/av/takeScreenshot'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            host_name: host.host_name,
            device_id: device.device_id,
          }),
        });
        if (!response.ok) {
          showError('Failed to capture image for AI query');
          return;
        }
        const result = await response.json();
        if (result.success && result.screenshot_url) {
          setCapturedImageUrl(result.screenshot_url);
          setIsImageQueryVisible(true);
        } else {
          showError('Failed to capture image for AI query');
        }
      } catch {
        showError('Failed to capture image for AI query');
      }
      return;
    }

    if (!currentSegmentUrl) return;

    const captureUrl = await getCaptureUrlFromStream(currentSegmentUrl, device ?? undefined, host);
    if (captureUrl) {
      setCapturedImageUrl(captureUrl);
      setIsImageQueryVisible(true);
    } else {
      showError('Could not determine current frame');
    }
  }, [host, device, currentSegmentUrl, isLiveMode, restartMode, showError]);

  return {
    capturedImageUrl,
    isImageQueryVisible,
    handleScreenshot,
    handleAIImageQuery,
    closeImageQuery,
  };
};
