import { useState, useCallback, useRef, useEffect, type MouseEvent } from 'react';

import { Host } from '../../types/common/Host_Types';
import { buildServerUrl, getStreamMediaSequence, pollForFreshStream } from '../../utils/buildUrlUtils';

export type QualityLevel = 'low' | 'sd' | 'hd' | 'hd_plus';

// Last-known stream quality per host+device, kept alive across modal open/close
// for the page session. Seeds the toggle's initial state so reopening the modal
// shows the real quality immediately instead of flashing the 'low' default
// until the async fetch resolves.
const qualityCache = new Map<string, QualityLevel>();
const qualityCacheKey = (hostName: string, deviceId: string) =>
  `${hostName}:${deviceId}`;

export interface RecQualitySwitchState {
  currentQuality: QualityLevel;
  isQualitySwitching: boolean;
  shouldPausePlayer: boolean;
}


export interface RecQualitySwitchActions {
  handleQualityChange: (
    _event: MouseEvent<HTMLElement>,
    newQuality: QualityLevel | null
  ) => Promise<void>;
  handlePlayerReady: () => void;
  switchQuality: (
    targetQuality: QualityLevel,
    showLoadingOverlay?: boolean,
    isInitialLoad?: boolean
  ) => Promise<void>;
  resetOnClose: () => void;
  stopPolling: () => void;
}


/**
 * Manages REC modal quality switching (LOW/SD/HD) with polling for stream readiness.
 */
export const useRecQualitySwitch = (
  host: Host,
  deviceId: string,
  showError: (msg: string) => void
): RecQualitySwitchState & RecQualitySwitchActions => {
  const cacheKeyRef = useRef<string>(qualityCacheKey(host.host_name, deviceId));
  const [currentQuality, setCurrentQuality] = useState<QualityLevel>(
    () => qualityCache.get(cacheKeyRef.current) ?? 'low'
  );
  const [isQualitySwitching, setIsQualitySwitching] = useState<boolean>(false);
  const [shouldPausePlayer, setShouldPausePlayer] = useState<boolean>(false);
  const isQualitySwitchingRef = useRef<boolean>(false);
  const pollingIntervalRef = useRef<(() => void) | NodeJS.Timeout | null>(null);
  const qualitySwitchRetryCountRef = useRef<number>(0);
  const hasUserSwitchedRef = useRef<boolean>(false);

  // On open, sync the toggle to the stream's actual quality (shared per-device
  // on the host) instead of the hardcoded 'low' default. Fetch at mount so a
  // user switch that lands first is never overwritten by the stale fetch.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(
          buildServerUrl(
            `/server/system/getStreamQuality?host_name=${encodeURIComponent(
              host.host_name
            )}&device_id=${encodeURIComponent(deviceId)}`
          )
        );
        if (!response.ok) return;
        const result = await response.json();
        const q = result?.quality as QualityLevel | undefined;
        if (q === 'low' || q === 'sd' || q === 'hd' || q === 'hd_plus') {
          qualityCache.set(qualityCacheKey(host.host_name, deviceId), q);
          if (!cancelled && !hasUserSwitchedRef.current) {
            setCurrentQuality(q);
          }
        }
      } catch {
        // Keep the default toggle state if the lookup fails.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [host.host_name, deviceId]);

  const setIsQualitySwitchingState = useCallback((value: boolean) => {
    isQualitySwitchingRef.current = value;
    setIsQualitySwitching(value);
  }, []);

  const stopPolling = useCallback(() => {
    if (pollingIntervalRef.current) {
      if (typeof pollingIntervalRef.current === 'function') {
        pollingIntervalRef.current();
      } else {
        clearInterval(pollingIntervalRef.current);
      }
      pollingIntervalRef.current = null;
    }
  }, []);

  const pollForNewStream = useCallback(
    (targetQuality: QualityLevel, baselineSequence: number) => {
      const cleanup = pollForFreshStream(
        host,
        deviceId,
        () => {
          qualitySwitchRetryCountRef.current = 0;
          setShouldPausePlayer(false);
          pollingIntervalRef.current = null;
        },
        (_error: string) => {
          if (qualitySwitchRetryCountRef.current === 0) {
            qualitySwitchRetryCountRef.current = 1;
            pollingIntervalRef.current = null;
            setTimeout(async () => {
              try {
                const retryBaseline = await getStreamMediaSequence(host, deviceId);
                const response = await fetch(buildServerUrl('/server/system/setStreamQuality'), {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    host_name: host.host_name,
                    device_id: deviceId,
                    quality: targetQuality,
                  }),
                });
                if (response.ok) {
                  pollForNewStream(targetQuality, retryBaseline);
                } else {
                  qualitySwitchRetryCountRef.current = 0;
                  setShouldPausePlayer(false);
                  setIsQualitySwitchingState(false);
                  showError(`Failed to switch to ${targetQuality.toUpperCase()} quality after retry`);
                }
              } catch {
                qualitySwitchRetryCountRef.current = 0;
                setShouldPausePlayer(false);
                setIsQualitySwitchingState(false);
                showError(`Failed to switch to ${targetQuality.toUpperCase()} quality after retry`);
              }
            }, 1000);
          } else {
            qualitySwitchRetryCountRef.current = 0;
            setShouldPausePlayer(false);
            setIsQualitySwitchingState(false);
            showError(
              `Stream failed to reload after switching to ${targetQuality.toUpperCase()} quality. Please try again.`
            );
            pollingIntervalRef.current = null;
          }
        },
        baselineSequence
      );
      pollingIntervalRef.current = cleanup as (() => void) | NodeJS.Timeout;
    },
    [host, deviceId, showError, setIsQualitySwitchingState]
  );

  const switchQuality = useCallback(
    async (
      targetQuality: QualityLevel,
      showLoadingOverlay = true,
      isInitialLoad = false
    ) => {
      hasUserSwitchedRef.current = true;
      qualityCache.set(qualityCacheKey(host.host_name, deviceId), targetQuality);
      stopPolling();
      setCurrentQuality(targetQuality);

      if (showLoadingOverlay) {
        setIsQualitySwitchingState(true);
        if (!isInitialLoad) {
          setShouldPausePlayer(true);
        }
      }

      try {
        // Capture the live stream's media sequence BEFORE the switch so the
        // restarted stream can be detected (FFmpeg resumes numbering forward,
        // never resetting to a low sequence — see pollForFreshStream).
        const baselineSequence = await getStreamMediaSequence(host, deviceId);

        const response = await fetch(buildServerUrl('/server/system/setStreamQuality'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            host_name: host.host_name,
            device_id: deviceId,
            quality: targetQuality,
          }),
        });

        if (response.ok && showLoadingOverlay) {
          pollForNewStream(targetQuality, baselineSequence);
        } else if (!response.ok && showLoadingOverlay) {
          showError(`Failed to switch to ${targetQuality.toUpperCase()} quality`);
          setShouldPausePlayer(false);
          setIsQualitySwitchingState(false);
        }
      } catch {
        if (showLoadingOverlay) {
          showError(`Failed to switch to ${targetQuality.toUpperCase()} quality`);
          setShouldPausePlayer(false);
          setIsQualitySwitchingState(false);
        }
      }
    },
    [host, deviceId, showError, stopPolling, pollForNewStream, setIsQualitySwitchingState]
  );

  const handleQualityChange = useCallback(
    async (_event: MouseEvent<HTMLElement>, newQuality: QualityLevel | null) => {
      if (!newQuality || newQuality === currentQuality) return;
      await switchQuality(newQuality, true, false);
    },
    [currentQuality, switchQuality]
  );

  const handlePlayerReady = useCallback(() => {
    if (isQualitySwitchingRef.current) {
      setIsQualitySwitchingState(false);
    }
  }, [setIsQualitySwitchingState]);

  const resetOnClose = useCallback(() => {
    stopPolling();
    setShouldPausePlayer(false);
    setIsQualitySwitchingState(false);
  }, [stopPolling, setIsQualitySwitchingState]);

  return {
    currentQuality,
    isQualitySwitching,
    shouldPausePlayer,
    handleQualityChange,
    handlePlayerReady,
    switchQuality,
    resetOnClose,
    stopPolling,
  };
};
