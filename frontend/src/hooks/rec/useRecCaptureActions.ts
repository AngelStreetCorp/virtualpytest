import { useState, useCallback } from 'react';

import { useToast } from '../useToast';
import { Host, Device } from '../../types/common/Host_Types';
import type { LiveStreamTransport } from '../../types/controller/WebRTC_Types';
import { buildServerUrl, getCaptureUrlFromStream, openHostUrl } from '../../utils/buildUrlUtils';

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
 * Uses the HLS segment when the player reports one, else the host screenshot API (always for VNC and WebRTC).
 */
export const useRecCaptureActions = (
  host: Host,
  device: Device | undefined,
  currentSegmentUrl: string | null,
  isLiveMode: boolean,
  restartMode: boolean,
  streamTransport: LiveStreamTransport
): RecCaptureActionsState & RecCaptureActionsActions => {
  const [capturedImageUrl, setCapturedImageUrl] = useState<string | null>(null);
  const [isImageQueryVisible, setIsImageQueryVisible] = useState(false);
  const { showError } = useToast();

  const closeImageQuery = useCallback(() => {
    setIsImageQueryVisible(false);
  }, []);

  // The latest frame straight from the host. VNC devices always use it; HLS devices use it when
  // the player has not reported a segment (the modal reuses the preview tile's stream, which has
  // no HLS player of its own). fast skips the host-side fingerprint pass (~1 s) the UI never reads.
  const fetchHostScreenshotUrl = useCallback(async (): Promise<string | null> => {
    if (!device) return null;
    try {
      const response = await fetch(buildServerUrl('/server/av/takeScreenshot'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host_name: host.host_name,
          device_id: device.device_id,
          fast: true,
        }),
      });
      if (!response.ok) return null;
      const result = await response.json();
      if (!result.success || !result.screenshot_url) return null;
      // The host overwrites one fixed file (verification_source.jpg) and serves it with a 4 h
      // max-age, so without a fresh query every click would show the first image again.
      const sep = result.screenshot_url.includes('?') ? '&' : '?';
      return `${result.screenshot_url}${sep}t=${Date.now()}`;
    } catch {
      return null;
    }
  }, [host, device]);

  const resolveFrameUrl = useCallback(async (): Promise<string | null> => {
    // WebRTC plays no HLS segments, so any segment URL left over from before the switch is stale.
    const useHostApi = device?.device_model === 'host_vnc' || streamTransport === 'webrtc';
    if (useHostApi || !currentSegmentUrl) return fetchHostScreenshotUrl();
    return getCaptureUrlFromStream(currentSegmentUrl, device ?? undefined, host);
  }, [host, device, currentSegmentUrl, streamTransport, fetchHostScreenshotUrl]);

  const handleScreenshot = useCallback(async () => {
    if (!isLiveMode || restartMode) {
      showError('Screenshot is only available in Live mode');
      return;
    }
    const url = await resolveFrameUrl();
    if (url) {
      await openHostUrl(url);
    } else {
      showError('Failed to take screenshot');
    }
  }, [isLiveMode, restartMode, resolveFrameUrl, showError]);

  const handleAIImageQuery = useCallback(async () => {
    if (!isLiveMode || restartMode) return;
    const url = await resolveFrameUrl();
    if (url) {
      setCapturedImageUrl(url);
      setIsImageQueryVisible(true);
    } else {
      showError('Failed to capture image for AI query');
    }
  }, [isLiveMode, restartMode, resolveFrameUrl, showError]);

  return {
    capturedImageUrl,
    isImageQueryVisible,
    handleScreenshot,
    handleAIImageQuery,
    closeImageQuery,
  };
};
